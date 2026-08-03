import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_ANIMATED_APPEND_CHARS,
  WORD_REVEAL_DURATION_MS,
  WORD_REVEAL_MAX_LAG_MS,
  WORD_REVEAL_STAGGER_MS,
  WordRevealTimeline,
  clampToWordBoundary,
  segmentRevealWords,
} from "../lib/chat_page/streaming_word_reveal";

test("segmentRevealWords groups Latin runs and excludes whitespace", () => {
  const text = "Hello brave world";
  const words = segmentRevealWords(text).map((word) => text.slice(word.start, word.end));

  assert.deepEqual(words, ["Hello", "brave", "world"]);
});

test("segmentRevealWords splits CJK into single characters", () => {
  const text = "こんにちは world";
  const words = segmentRevealWords(text).map((word) => text.slice(word.start, word.end));

  assert.deepEqual(words, ["こ", "ん", "に", "ち", "は", "world"]);
});

test("segmentRevealWords separates CJK from an adjacent Latin run", () => {
  const text = "AI技術";
  const words = segmentRevealWords(text).map((word) => text.slice(word.start, word.end));

  assert.deepEqual(words, ["AI", "技", "術"]);
});

test("segmentRevealWords keeps offsets aligned with the source text", () => {
  const text = "  ab  cd ";
  const words = segmentRevealWords(text);

  assert.deepEqual(words, [
    { start: 2, end: 4 },
    { start: 6, end: 8 },
  ]);
});

test("clampToWordBoundary hides a half-typed Latin word", () => {
  const text = "streaming words";
  assert.equal(clampToWordBoundary(text, 12), 10);
});

test("clampToWordBoundary keeps a length that already sits on a boundary", () => {
  const text = "streaming words";
  assert.equal(clampToWordBoundary(text, 9), 9);
  assert.equal(clampToWordBoundary(text, 10), 10);
});

test("clampToWordBoundary never holds back CJK text", () => {
  const text = "こんにちは世界";
  assert.equal(clampToWordBoundary(text, 3), 3);
});

test("clampToWordBoundary returns the full length once everything is revealed", () => {
  const text = "done";
  assert.equal(clampToWordBoundary(text, 4), 4);
  assert.equal(clampToWordBoundary(text, 9), 4);
  assert.equal(clampToWordBoundary(text, 0), 0);
});

test("clampToWordBoundary gives up on tokens longer than the lookback window", () => {
  const text = `${"a".repeat(200)}b`;
  assert.equal(clampToWordBoundary(text, 120), 120);
});

test("clampToWordBoundary does not stall on a word that starts the text", () => {
  const text = "supercalifragilistic";
  assert.equal(clampToWordBoundary(text, 5), 5);
});

test("WordRevealTimeline reports elapsed time and retires finished words", () => {
  const timeline = new WordRevealTimeline();
  timeline.sync("a".repeat(50));

  assert.equal(timeline.elapsedFor(10, 1000), 0);
  assert.equal(timeline.elapsedFor(10, 1100), 100);
  assert.equal(timeline.elapsedFor(10, 1000 + WORD_REVEAL_DURATION_MS), null);
});

test("WordRevealTimeline keeps prefix schedules when the text truncates", () => {
  const timeline = new WordRevealTimeline();
  timeline.sync("a".repeat(50));
  timeline.elapsedFor(10, 1000);

  timeline.sync("a".repeat(20));

  // 切り詰め後も、共通接頭辞に残った語のアニメーションは巻き戻らない。
  // A word that survived the truncation keeps playing instead of restarting.
  assert.equal(timeline.elapsedFor(10, 1200), 200);
});

test("WordRevealTimeline keeps offsets while the text only grows", () => {
  const timeline = new WordRevealTimeline();
  timeline.sync("a".repeat(50));
  timeline.elapsedFor(10, 1000);

  timeline.sync("a".repeat(80));

  assert.equal(timeline.elapsedFor(10, 1100), 100);
});

test("WordRevealTimeline shifts schedules across a markdown reflow", () => {
  const timeline = new WordRevealTimeline();
  // "Streaming **bold now" → 整形確定で "Streaming bold now" になるケース。
  // The `**` collapses when markdown finalizes, shifting later offsets by -2.
  timeline.sync("Streaming **bold now");
  timeline.elapsedFor(0, 1000);
  timeline.elapsedFor(17, 1000);

  timeline.sync("Streaming bold now");

  // 差し替え位置より前の語はそのまま、後ろの語は差分だけずれて引き継がれる。
  // Words before the edit keep their slot; later ones shift by the delta.
  assert.equal(timeline.elapsedFor(0, 1100), 100);
  assert.equal(timeline.elapsedFor(15, 1100), 100 - WORD_REVEAL_STAGGER_MS);
});

test("WordRevealTimeline staggers words that arrive in the same frame", () => {
  const timeline = new WordRevealTimeline();
  timeline.sync("a".repeat(100));

  // 同時に届いた語でも開始時刻が1語ずつ後ろへずれ、カスケードになる。
  // Words seen at the same instant still start one stagger step apart.
  assert.equal(timeline.elapsedFor(0, 1000), 0);
  assert.equal(timeline.elapsedFor(6, 1000), -WORD_REVEAL_STAGGER_MS);
  assert.equal(timeline.elapsedFor(12, 1000), -WORD_REVEAL_STAGGER_MS * 2);
});

test("WordRevealTimeline caps how far the cascade may trail the text", () => {
  const timeline = new WordRevealTimeline();
  timeline.sync("a".repeat(200));

  let last: number | null = 0;
  for (let word = 0; word * 6 < 200; word += 1) {
    last = timeline.elapsedFor(word * 6, 1000);
  }

  // 上限を超えた語は上限位置へ畳まれ、表示が生成へ遅れ続けない。
  // Words past the cap collapse onto it, so the reveal never falls behind.
  assert.equal(last, -WORD_REVEAL_MAX_LAG_MS);
});

test("WordRevealTimeline never replays a word whose schedule was pruned", () => {
  const timeline = new WordRevealTimeline();
  timeline.sync("a".repeat(100));
  timeline.elapsedFor(10, 1000);
  timeline.sync("a".repeat(300));
  timeline.sync("a".repeat(500));
  assert.equal(timeline.elapsedFor(400, 1000), -WORD_REVEAL_STAGGER_MS);

  timeline.prune(300);

  // 予約を失った表示済みの語は「新規」へ戻さず即表示扱いにする。以前は未来の
  // 開始時刻で再登録され、表示済みテキストが点滅してもう一度フェードしていた。
  // A visible word whose record was pruned counts as already shown. It used to
  // be re-scheduled in the future, blinking and fading in again.
  assert.equal(timeline.elapsedFor(10, 1100), null);
  assert.equal(timeline.elapsedFor(400, 1100), 100 - WORD_REVEAL_STAGGER_MS);
});

test("WordRevealTimeline treats known words without a schedule as already visible", () => {
  const timeline = new WordRevealTimeline();
  timeline.sync("hello world");
  timeline.sync("hello world again");

  // 既知コンテンツ内で予約が無い語（追跡漏れ）は透明に戻さない。
  // An untracked word inside known content must never turn transparent.
  assert.equal(timeline.elapsedFor(6, 1000), null);
  // 新しく追記された語は通常どおりアニメーションする。
  // Freshly appended words still animate.
  assert.equal(timeline.elapsedFor(12, 1000), 0);
});

test("WordRevealTimeline shows a bulk append instantly instead of replaying it", () => {
  const timeline = new WordRevealTimeline();
  timeline.sync("a".repeat(MAX_ANIMATED_APPEND_CHARS + 100));

  // パーツ更新や復元で一括到着したテキストは、後からまとめてフェードさせない。
  // Text that lands in bulk (parts update, restore) must not fade afterwards.
  assert.equal(timeline.elapsedFor(0, 1000), null);
  assert.equal(timeline.elapsedFor(300, 1000), null);
});
