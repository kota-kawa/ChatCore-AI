import assert from "node:assert/strict";
import test from "node:test";

import {
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
  timeline.sync(50);

  assert.equal(timeline.elapsedFor(10, 1000), 0);
  assert.equal(timeline.elapsedFor(10, 1100), 100);
  assert.equal(timeline.elapsedFor(10, 1000 + WORD_REVEAL_DURATION_MS), null);
});

test("WordRevealTimeline forgets offsets when the text shrinks", () => {
  const timeline = new WordRevealTimeline();
  timeline.sync(50);
  timeline.elapsedFor(10, 1000);

  timeline.sync(20);

  assert.equal(timeline.elapsedFor(10, 1200), 0);
});

test("WordRevealTimeline keeps offsets while the text only grows", () => {
  const timeline = new WordRevealTimeline();
  timeline.sync(50);
  timeline.elapsedFor(10, 1000);

  timeline.sync(80);

  assert.equal(timeline.elapsedFor(10, 1100), 100);
});

test("WordRevealTimeline staggers words that arrive in the same frame", () => {
  const timeline = new WordRevealTimeline();
  timeline.sync(100);

  // 同時に届いた語でも開始時刻が1語ずつ後ろへずれ、カスケードになる。
  // Words seen at the same instant still start one stagger step apart.
  assert.equal(timeline.elapsedFor(0, 1000), 0);
  assert.equal(timeline.elapsedFor(6, 1000), -WORD_REVEAL_STAGGER_MS);
  assert.equal(timeline.elapsedFor(12, 1000), -WORD_REVEAL_STAGGER_MS * 2);
});

test("WordRevealTimeline caps how far the cascade may trail the text", () => {
  const timeline = new WordRevealTimeline();
  timeline.sync(10000);

  let last: number | null = 0;
  for (let word = 0; word < 200; word += 1) {
    last = timeline.elapsedFor(word * 6, 1000);
  }

  // 上限を超えた語は上限位置へ畳まれ、表示が生成へ遅れ続けない。
  // Words past the cap collapse onto it, so the reveal never falls behind.
  assert.equal(last, -WORD_REVEAL_MAX_LAG_MS);
});

test("WordRevealTimeline prunes only records outside the animated tail", () => {
  const timeline = new WordRevealTimeline();
  timeline.sync(500);
  timeline.elapsedFor(10, 1000);
  assert.equal(timeline.elapsedFor(400, 1000), -WORD_REVEAL_STAGGER_MS);

  timeline.prune(300);

  // 末尾から外れた語だけが捨てられ、画面に残っている語は再登録されない。
  // Only the word that left the tail is dropped; the on-screen one is kept.
  assert.equal(timeline.elapsedFor(10, 1100), 0);
  assert.equal(timeline.elapsedFor(400, 1100), 100 - WORD_REVEAL_STAGGER_MS);
});
