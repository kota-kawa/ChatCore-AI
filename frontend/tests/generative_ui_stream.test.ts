import assert from "node:assert/strict";
import test from "node:test";

import {
  getStreamingGenerativeUiDisplayText,
  generativeUiFenceKind,
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

test("legacy artifact aliases are hidden but still show that a UI is being produced", () => {
  const text = [
    "```ui_artifact",
    '{"version":1,"title":"UI"',
  ].join("\n");

  // 本文から隠したうえで何も出さないと、回答が消えたように見える。実行できないことは
  // 最終的な artifact_status で伝える。
  // Hiding the fence and showing nothing made the answer look like it vanished; the fact that
  // it cannot execute is delivered by the final artifact_status.
  assert.equal(getStreamingGenerativeUiDisplayText(text), "");
  assert.equal(isGenerativeUiPending(text), true);
  assert.equal(generativeUiFenceKind(text), "probable");
  assert.equal(generativeUiFenceKind("説明\n```chatcore-artifact\n{"), "exact");
  assert.equal(generativeUiFenceKind("ただのテキストです。"), null);
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
  assert.equal(hasGenerativeUiFenceStart("説明\n```chatcore-artifact json\n{"), true);
  assert.equal(hasGenerativeUiFenceStart("説明\n```generative-ui json\n{"), false);
  assert.equal(hasGenerativeUiFenceStart("```chatcore-buttons\n"), false);
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

const ANSWER_TRACE = [
  '<details class="web-search-sources web-search-sources--trace">',
  '<summary class="web-search-sources__summary">回答までのステップ</summary>',
  '<div class="web-search-sources__list">参照したWebサイト</div>',
  "</details>",
].join("\n");

const INLINE_IMAGE: ChatMessagePart = {
  type: "web_search_image",
  image: {
    url: "https://cdn.example.com/momiji.jpg",
    alt: "紅葉の写真",
    sourceUrl: "https://example.com/kyoto",
  },
};

test("updateStreamingTextPart absorbs the newlines dropped between the trace and the answer", () => {
  // パーツはトレースと本文の間の改行を落として届くが、ストリーム本文には残る。
  // 最後のパーツに全文が入ると、画像の下にトレースと見出しがもう一度出る。
  // Parts arrive without the newlines between the trace and the answer, but the
  // streamed text keeps them; the full text in the last part duplicated the trace.
  const parts: ChatMessagePart[] = [
    { type: "text", text: ANSWER_TRACE },
    { type: "text", text: "京都の紅葉" },
    INLINE_IMAGE,
    { type: "text", text: "" },
  ];

  const updated = updateStreamingTextPart(parts, `${ANSWER_TRACE}\n\n京都の紅葉は11月中旬が見頃です。`);

  assert.deepEqual(updated, [
    { type: "text", text: ANSWER_TRACE },
    { type: "text", text: "京都の紅葉" },
    INLINE_IMAGE,
    { type: "text", text: "は11月中旬が見頃です。" },
  ]);
});

test("updateStreamingTextPart keeps continuing when the separator newline is still in the parts", () => {
  const parts: ChatMessagePart[] = [
    { type: "text", text: "## 見頃と名所\n" },
    INLINE_IMAGE,
    { type: "text", text: "" },
  ];

  assert.deepEqual(updateStreamingTextPart(parts, "## 見頃と名所\n見頃は11月中旬です。"), [
    { type: "text", text: "## 見頃と名所\n" },
    INLINE_IMAGE,
    { type: "text", text: "見頃は11月中旬です。" },
  ]);
});

test("updateStreamingTextPart keeps the trace in the single text part when there is no image", () => {
  const text = `${ANSWER_TRACE}\n\n京都の紅葉は11月中旬が見頃です。`;

  assert.deepEqual(updateStreamingTextPart([{ type: "text", text: "" }], text), [{ type: "text", text }]);
});

test("updateStreamingTextPart continues after the trace when the streamed text hides a generative UI fence", () => {
  const parts: ChatMessagePart[] = [
    { type: "text", text: ANSWER_TRACE },
    { type: "text", text: "## 見頃と名所" },
    INLINE_IMAGE,
    { type: "text", text: "" },
  ];
  const streamed = [
    ANSWER_TRACE,
    "",
    "## 見頃と名所",
    "見頃は11月中旬です。",
    "```chatcore-artifact",
    '{"version":1,"title":"UI","html":"<div></div>","css":"","js":""}',
    "```",
    "混雑は平日の朝が少なめです。",
    "```chatcore-artifact",
    '{"version":1,"title":"UI","html":"<div',
  ].join("\n");

  const updated = updateStreamingTextPart(parts, getStreamingGenerativeUiDisplayText(streamed));

  assert.deepEqual(updated, [
    { type: "text", text: ANSWER_TRACE },
    { type: "text", text: "## 見頃と名所" },
    INLINE_IMAGE,
    { type: "text", text: "見頃は11月中旬です。\n\n混雑は平日の朝が少なめです。" },
  ]);
});
