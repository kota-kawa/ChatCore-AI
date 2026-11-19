// 引用チップを途中で切らない表示位置の補正を検証する。
// Tests that the revealed position never slices through a citation chip.

import assert from "node:assert/strict";
import test from "node:test";

import { normalizeCitationChipStreamBoundary } from "../lib/chat_page/stream_display_text";

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
