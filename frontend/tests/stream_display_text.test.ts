import assert from "node:assert/strict";
import test from "node:test";

import { splitStreamDisplayText } from "../lib/chat_page/stream_display_text";

test("separates a completed leading web-search trace from the paced answer", () => {
  const trace = [
    '<details class="web-search-sources web-search-sources--trace">',
    '<summary class="web-search-sources__summary">回答までのステップ</summary>',
    '<div class="web-search-sources__list">',
    '<details class="web-search-sources__step-details">',
    '<summary>Web検索: テスト</summary>',
    '<p>検索結果</p>',
    "</details>",
    "</div>",
    "</details>",
  ].join("\n");

  const result = splitStreamDisplayText(`\n${trace}\n\n実際の回答本文です。`);

  assert.match(result.instantPrefix, /回答までのステップ/);
  assert.match(result.instantPrefix, /<details class="web-search-sources__step-details">/);
  assert.equal(result.pacedText, "実際の回答本文です。");
});

test("keeps an incomplete web-search trace in the paced text", () => {
  const incomplete = [
    '<details class="web-search-sources web-search-sources--trace">',
    '<summary class="web-search-sources__summary">回答までのステップ</summary>',
    '<div class="web-search-sources__list">',
  ].join("\n");

  assert.deepEqual(splitStreamDisplayText(incomplete), {
    instantPrefix: "",
    pacedText: incomplete,
  });
});

test("does not bypass pacing for ordinary details in an answer", () => {
  const answer = "<details><summary>補足</summary><p>詳細</p></details>\n\n本文";

  assert.deepEqual(splitStreamDisplayText(answer), {
    instantPrefix: "",
    pacedText: answer,
  });
});

test("leaves plain streamed text unchanged", () => {
  const answer = "通常の回答本文です。";

  assert.deepEqual(splitStreamDisplayText(answer), {
    instantPrefix: "",
    pacedText: answer,
  });
});
