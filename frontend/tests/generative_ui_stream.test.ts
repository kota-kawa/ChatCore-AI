import assert from "node:assert/strict";
import test from "node:test";

import {
  getStreamingGenerativeUiDisplayText,
  hasGenerativeUiFenceStart,
  isGenerativeUiPending,
  stripGenerativeUiFencesForStreaming,
  updateStreamingTextPart,
} from "../lib/chat_page/generative_ui_stream";
import type { ChatMessagePart } from "../lib/chat_page/types";

test("stripGenerativeUiFencesForStreaming removes complete artifact fences", () => {
  const text = [
    "上の説明です。",
    "```chatcore-artifact",
    '{"version":1,"title":"UI","html":"<div></div>","css":"","js":""}',
    "```",
    "続きの説明です。",
  ].join("\n");

  const stripped = stripGenerativeUiFencesForStreaming(text);

  assert.equal(stripped, "上の説明です。\n\n続きの説明です。");
  assert.doesNotMatch(stripped, /chatcore-artifact/);
});

test("stripGenerativeUiFencesForStreaming removes supported artifact aliases", () => {
  const text = [
    "前置きです。",
    "```generative-ui json",
    '{"version":1,"title":"UI","html":"<div></div>","css":"","js":""}',
    "```",
    "```interactive-buttons",
    '{"type":"yes_no","question":"続けますか？"}',
    "```",
  ].join("\n");

  const stripped = stripGenerativeUiFencesForStreaming(text);

  assert.equal(stripped, "前置きです。");
  assert.doesNotMatch(stripped, /generative-ui|interactive-buttons/);
});

test("stripGenerativeUiFencesForStreaming removes malformed artifact fence names", () => {
  const text = [
    "前置きです。",
    "```chatcore artifact:",
    '{"version":1,"title":"UI","html":"<div></div>","css":"","js":""}',
    "```",
  ].join("\n");

  const stripped = stripGenerativeUiFencesForStreaming(text);

  assert.equal(stripped, "前置きです。");
  assert.doesNotMatch(stripped, /chatcore artifact|"version"/);
});

test("getStreamingGenerativeUiDisplayText hides incomplete artifact JSON while streaming", () => {
  const text = [
    "説明します。",
    "```chatcore-artifact",
    '{"version":1,"title":"UI","html":"<div',
  ].join("\n");

  assert.equal(getStreamingGenerativeUiDisplayText(text), "説明します。");
});

test("getStreamingGenerativeUiDisplayText returns empty text for alias-only artifact output", () => {
  // 進行表示は静的テキストではなく GenerativeUiLoader が担うため、本文は空になる。
  // The GenerativeUiLoader (not static text) now indicates progress, so the prose stays empty.
  const text = [
    "```ui_artifact",
    '{"version":1,"title":"UI"',
  ].join("\n");

  assert.equal(getStreamingGenerativeUiDisplayText(text), "");
  assert.equal(isGenerativeUiPending(text), true);
});

test("getStreamingGenerativeUiDisplayText returns empty text for artifact-only output", () => {
  const text = [
    "```chatcore-artifact",
    '{"version":1,"title":"UI"',
  ].join("\n");

  assert.equal(getStreamingGenerativeUiDisplayText(text), "");
  assert.equal(isGenerativeUiPending(text), true);
});

test("hasGenerativeUiFenceStart detects fence starts and ignores plain code fences", () => {
  assert.equal(hasGenerativeUiFenceStart("説明\n```generative-ui json\n{"), true);
  assert.equal(hasGenerativeUiFenceStart("```chatcore-buttons\n"), true);
  assert.equal(hasGenerativeUiFenceStart("```python\nprint(1)\n```"), false);
  assert.equal(hasGenerativeUiFenceStart("ただのテキストです。"), false);
});

test("isGenerativeUiPending stays true while streaming and turns false once a part arrives", () => {
  const text = [
    "作りますね。",
    "```chatcore-artifact",
    '{"version":1,"title":"UI","html":"<div',
  ].join("\n");

  assert.equal(isGenerativeUiPending(text), true);
  assert.equal(isGenerativeUiPending(text, [{ type: "text", text: "作りますね。" }]), true);

  const partsWithArtifact: ChatMessagePart[] = [
    { type: "text", text: "作りますね。" },
    {
      type: "sandbox_artifact",
      artifact: { version: 1, title: "UI", html: "<div></div>", css: "", js: "" },
    },
  ];
  assert.equal(isGenerativeUiPending(text, partsWithArtifact), false);
});

test("isGenerativeUiPending is false for plain text streams", () => {
  assert.equal(isGenerativeUiPending("こんにちは。普通の回答です。"), false);
  assert.equal(isGenerativeUiPending(""), false);
});

test("updateStreamingTextPart keeps artifact parts while refreshing streamed text", () => {
  const parts: ChatMessagePart[] = [
    { type: "text", text: "old" },
    {
      type: "sandbox_artifact",
      artifact: {
        version: 1,
        title: "UI",
        html: "<div></div>",
        css: "",
        js: "",
      },
    },
  ];

  const updated = updateStreamingTextPart(parts, "new");

  assert.equal(updated?.[0]?.type, "text");
  assert.deepEqual(updated?.[0], { type: "text", text: "new" });
  assert.equal(updated?.[1]?.type, "sandbox_artifact");
});
