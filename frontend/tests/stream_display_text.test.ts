import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeCitationChipStreamBoundary,
  splitStreamDisplayText,
} from "../lib/chat_page/stream_display_text";

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

test("advances through a complete citation chip instead of slicing its HTML", () => {
  const chip = '<a class="web-search-citation" href="https://example.com"><span>Example</span></a>';
  const answer = `本文${chip}続き`;
  const chipStart = answer.indexOf(chip);
  const chipEnd = chipStart + chip.length;
  const boundary = normalizeCitationChipStreamBoundary(answer, chipStart + 8);

  assert.equal(boundary, chipEnd);
  assert.equal(answer.slice(0, boundary), `本文${chip}`);
});

test("holds before an incomplete citation chip", () => {
  const answer = '本文<a class="web-search-citation" href="https://example.com"';
  assert.equal(normalizeCitationChipStreamBoundary(answer, answer.length), 2);
});
