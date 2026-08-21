import assert from "node:assert/strict";
import test from "node:test";

import {
  applyVisualPartContract,
  normalizeMessagePartsForDisplay,
  splitAnswerTraceBlock,
} from "../lib/chat_page/message_parts_display";
import { updateStreamingTextPart } from "../lib/chat_page/generative_ui_stream";
import type { ChatMessagePart } from "../lib/chat_page/types";

const TRACE = [
  '<details class="web-search-sources web-search-sources--trace">',
  '<summary class="web-search-sources__summary">',
  '<span class="web-search-sources__label">回答までのステップ</span>',
  "</summary>",
  '<div class="web-search-sources__list">',
  '<details class="web-search-sources__step-details">',
  '<summary class="web-search-sources__step-summary">Web検索</summary>',
  '<div class="web-search-sources__step-body">参照したWebサイト</div>',
  "</details>",
  "</div>",
  "</details>",
].join("\n");

const IMAGE_PART: ChatMessagePart = {
  type: "web_search_image",
  image: {
    url: "https://cdn.example.com/hero.jpg",
    alt: "Relevant photo",
    sourceUrl: "https://example.com/article",
  },
};

test("splitAnswerTraceBlock keeps nested step details inside the trace", () => {
  const { trace, remainder } = splitAnswerTraceBlock(`${TRACE}\n\nanswer`);

  assert.equal(trace, TRACE);
  assert.equal(remainder, "answer");
});

test("splitAnswerTraceBlock returns text without a trace unchanged", () => {
  const { trace, remainder } = splitAnswerTraceBlock("answer only");

  assert.equal(trace, "");
  assert.equal(remainder, "answer only");
});

test("normalizeMessagePartsForDisplay puts the image below the answer trace", () => {
  const parts: ChatMessagePart[] = [IMAGE_PART, { type: "text", text: `${TRACE}\n\nanswer` }];

  const normalized = normalizeMessagePartsForDisplay(parts);

  assert.deepEqual(normalized, [
    { type: "text", text: TRACE },
    IMAGE_PART,
    { type: "text", text: "answer" },
  ]);
  assert.deepEqual(normalizeMessagePartsForDisplay(normalized), normalized);
});

test("normalizeMessagePartsForDisplay keeps the image above an answer without a trace", () => {
  const parts: ChatMessagePart[] = [{ type: "text", text: "answer" }, IMAGE_PART];

  assert.deepEqual(normalizeMessagePartsForDisplay(parts), [IMAGE_PART, { type: "text", text: "answer" }]);
});

test("applyVisualPartContract never splits the trace off the answer text", () => {
  const textPart: ChatMessagePart = { type: "text", text: `${TRACE}\n\nanswer` };

  assert.deepEqual(applyVisualPartContract([textPart, IMAGE_PART]), [IMAGE_PART, textPart]);
});

test("updateStreamingTextPart re-splits the trace instead of duplicating the answer", () => {
  const parts: ChatMessagePart[] = [
    { type: "text", text: TRACE },
    IMAGE_PART,
    { type: "text", text: "answer" },
  ];

  const updated = updateStreamingTextPart(parts, `${TRACE}\n\nanswer 2`);

  assert.deepEqual(updated, [
    { type: "text", text: TRACE },
    IMAGE_PART,
    { type: "text", text: "answer 2" },
  ]);
});
