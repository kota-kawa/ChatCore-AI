import assert from "node:assert/strict";
import test from "node:test";

import {
  getStreamingGenerativeUiDisplayText,
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

test("getStreamingGenerativeUiDisplayText hides incomplete artifact JSON while streaming", () => {
  const text = [
    "説明します。",
    "```chatcore-artifact",
    '{"version":1,"title":"UI","html":"<div',
  ].join("\n");

  assert.equal(getStreamingGenerativeUiDisplayText(text), "説明します。");
});

test("getStreamingGenerativeUiDisplayText shows progress for alias-only artifact output", () => {
  const text = [
    "```ui_artifact",
    '{"version":1,"title":"UI"',
  ].join("\n");

  assert.equal(getStreamingGenerativeUiDisplayText(text), "生成UIを作成中です...");
});

test("getStreamingGenerativeUiDisplayText shows an in-progress label for artifact-only output", () => {
  const text = [
    "```chatcore-artifact",
    '{"version":1,"title":"UI"',
  ].join("\n");

  assert.equal(getStreamingGenerativeUiDisplayText(text), "生成UIを作成中です...");
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
