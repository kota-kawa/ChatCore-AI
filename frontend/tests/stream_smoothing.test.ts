import assert from "node:assert/strict";
import test from "node:test";

import {
  clampToCodePointBoundary,
  nextSmoothedLength,
} from "../lib/chat_page/stream_smoothing";

test("nextSmoothedLength reveals at least the minimum step", () => {
  assert.equal(nextSmoothedLength(0, 1), 1);
  assert.equal(nextSmoothedLength(0, 2), 2);
  assert.equal(nextSmoothedLength(0, 10), 2);
  assert.equal(nextSmoothedLength(5, 10), 7);
});

test("nextSmoothedLength drains a large backlog proportionally", () => {
  const step = nextSmoothedLength(0, 1000);
  assert.ok(step > 100, `expected proportional drain, got ${step}`);
  assert.ok(step < 1000, "must not flush the whole backlog at once");
});

test("nextSmoothedLength never overshoots the target", () => {
  assert.equal(nextSmoothedLength(999, 1000), 1000);
  assert.equal(nextSmoothedLength(10, 10), 10);
});

test("nextSmoothedLength snaps down when the target shrinks", () => {
  assert.equal(nextSmoothedLength(50, 30), 30);
  assert.equal(nextSmoothedLength(50, 0), 0);
});

test("nextSmoothedLength converges to the target from any distance", () => {
  let current = 0;
  let frames = 0;
  while (current < 5000 && frames < 1000) {
    current = nextSmoothedLength(current, 5000);
    frames += 1;
  }
  assert.equal(current, 5000);
  assert.ok(frames < 100, `expected fast convergence, took ${frames} frames`);
});

test("clampToCodePointBoundary keeps surrogate pairs intact", () => {
  const text = "ab😀cd";
  // "😀" は index 2-3 のサロゲートペア。3 で切るとペアが割れるため 4 へ進む。
  assert.equal(clampToCodePointBoundary(text, 3), 4);
  assert.equal(clampToCodePointBoundary(text, 2), 2);
  assert.equal(clampToCodePointBoundary(text, 4), 4);
});

test("clampToCodePointBoundary clamps out-of-range lengths", () => {
  assert.equal(clampToCodePointBoundary("abc", -1), 0);
  assert.equal(clampToCodePointBoundary("abc", 0), 0);
  assert.equal(clampToCodePointBoundary("abc", 5), 3);
});
