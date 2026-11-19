// 回答を構成する本文以外のパーツ表示を検証する。
// Tests message parts display behavior.

import assert from "node:assert/strict";
import test from "node:test";

import {
  applyVisualPartContract,
  normalizeMessagePartsForDisplay,
} from "../lib/chat_page/message_parts_display";
import { updateStreamingTextPart } from "../lib/chat_page/generative_ui_stream";
import type { ChatMessagePart } from "../lib/chat_page/types";
import { makeTrace } from "./answer_trace_test_data";

const IMAGE_PART: ChatMessagePart = {
  type: "web_search_image",
  image: {
    url: "https://cdn.example.com/hero.jpg",
    alt: "Relevant photo",
    sourceUrl: "https://example.com/article",
  },
};

test("the display order puts the trace first (structured or legacy) and drops a second one", () => {
  const text: ChatMessagePart = { type: "text", text: "本文" };
  const first: ChatMessagePart = { type: "answer_trace", trace: makeTrace() };
  const legacy: ChatMessagePart = { type: "legacy_answer_trace", html: "<details></details>" };

  assert.deepEqual(normalizeMessagePartsForDisplay([text, first]), [first, text]);
  assert.deepEqual(normalizeMessagePartsForDisplay([text, legacy]), [legacy, text]);
  assert.deepEqual(normalizeMessagePartsForDisplay([text, first, legacy]), [first, text]);
  assert.deepEqual(normalizeMessagePartsForDisplay([legacy, text, first]), [legacy, text]);
  assert.deepEqual(normalizeMessagePartsForDisplay([text]), [text]);
});

test("a legacy image saved before the trace is not reordered by the client", () => {
  // サーバーが読み出し時にトレース直下へ移す。クライアントは受け取った順序を保つ。
  // The server moves it below the trace on read; the client keeps the order it received.
  const image: ChatMessagePart = {
    type: "web_search_image",
    image: { url: "https://cdn.example.com/a.jpg", alt: "a", sourceUrl: "https://example.com/a" },
  };
  const trace: ChatMessagePart = { type: "answer_trace", trace: makeTrace() };
  const text: ChatMessagePart = { type: "text", text: "本文" };

  assert.deepEqual(normalizeMessagePartsForDisplay([trace, image, text]), [trace, image, text]);
});

test("normalizeMessagePartsForDisplay preserves inline order", () => {
  const parts: ChatMessagePart[] = [{ type: "text", text: "answer" }, IMAGE_PART];

  assert.deepEqual(normalizeMessagePartsForDisplay(parts), [{ type: "text", text: "answer" }, IMAGE_PART]);
});

test("applyVisualPartContract keeps at most five web-search images", () => {
  const images = Array.from({ length: 6 }, (_, index) => ({
    ...IMAGE_PART,
    image: { ...IMAGE_PART.image, url: `https://cdn.example.com/hero-${index}.jpg` },
  }));

  const normalized = applyVisualPartContract(images);

  assert.equal(normalized.filter((part) => part.type === "web_search_image").length, 5);
});

test("updateStreamingTextPart keeps inline images while extending the trailing text", () => {
  const parts: ChatMessagePart[] = [
    { type: "text", text: "明月院" },
    IMAGE_PART,
    { type: "text", text: "" },
  ];

  assert.deepEqual(updateStreamingTextPart(parts, "明月院 説明です。"), [
    { type: "text", text: "明月院" },
    IMAGE_PART,
    { type: "text", text: " 説明です。" },
  ]);
});

test("choice buttons never suppress web-search images", () => {
  const parts: ChatMessagePart[] = [
    { type: "text", text: "明月院" },
    IMAGE_PART,
    { type: "text", text: "どちらを詳しく知りたいですか。" },
    { type: "interactive_buttons", buttons: { type: "multiple_choice", question: "どちらにしますか？", options: ["明月院", "東慶寺"] } },
  ];

  assert.deepEqual(applyVisualPartContract(parts), parts);
  assert.deepEqual(normalizeMessagePartsForDisplay(parts), parts);
});
