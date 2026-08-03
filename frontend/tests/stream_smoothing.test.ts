import assert from "node:assert/strict";
import test from "node:test";

import {
  advanceStreamPace,
  clampToCodePointBoundary,
  createStreamPace,
} from "../lib/chat_page/stream_smoothing";

const FRAME_MS = 16;

test("advanceStreamPace reveals text and never overshoots the target", () => {
  const pace = createStreamPace(0, 0);
  let length = 0;
  for (let now = FRAME_MS; now <= 2000; now += FRAME_MS) {
    const next = advanceStreamPace(pace, 100, now);
    assert.ok(next >= length, "the visible length must be monotonic");
    assert.ok(next <= 100, "the visible length must never pass the target");
    length = next;
  }
  assert.equal(length, 100);
});

test("advanceStreamPace keeps a near-constant speed under steady chunks", () => {
  const pace = createStreamPace(0, 0);
  const settledSteps: number[] = [];
  let previous = 0;
  let previousStep = 0;
  for (let now = FRAME_MS; now <= 5000; now += FRAME_MS) {
    // 100ms ごとに30文字のチャンクが届く定常ストリーム（300文字/秒）。
    // A steady stream: a 30-char chunk every 100ms (300 chars/s).
    const target = Math.floor(now / 100) * 30;
    const next = advanceStreamPace(pace, target, now);
    const step = next - previous;
    if (now > 200) {
      // チャンク到着の瞬間でも隣接フレームの進みが跳ねない（急加速・急停止なし）。
      // Adjacent frames never jump, even on chunk arrival: no surge, no stall.
      assert.ok(
        Math.abs(step - previousStep) <= 2,
        `adjacent steps must stay smooth at t=${now} (${previousStep} -> ${step})`,
      );
    }
    if (now > 3000) settledSteps.push(step);
    previous = next;
    previousStep = step;
  }
  const max = Math.max(...settledSteps);
  const min = Math.min(...settledSteps);
  // 収束後は丸め誤差程度のブレしか残らない。
  // Once settled, only rounding-level variation remains.
  assert.ok(max - min <= 2, `settled steps should be near-constant, saw min=${min} max=${max}`);
});

test("advanceStreamPace does not surge when a large chunk lands", () => {
  const pace = createStreamPace(0, 0);
  let previous = 0;
  let steadyStep = 0;
  for (let now = FRAME_MS; now <= 1000; now += FRAME_MS) {
    const target = Math.floor((now / 1000) * 300);
    const next = advanceStreamPace(pace, target, now);
    steadyStep = Math.max(steadyStep, next - previous);
    previous = next;
  }
  // 1000ms 時点で残り600文字のバーストが届く。
  // A burst leaving a 600-char backlog lands at 1000ms.
  const next = advanceStreamPace(pace, 900, 1000 + FRAME_MS);
  const burstStep = next - previous;
  assert.ok(
    burstStep <= Math.max(steadyStep * 2, 4),
    `a burst must not multiply the speed at once (steady=${steadyStep}, burst=${burstStep})`,
  );
});

test("advanceStreamPace snaps down when the target shrinks", () => {
  const pace = createStreamPace(50, 0);
  assert.equal(advanceStreamPace(pace, 30, FRAME_MS), 30);
  assert.equal(advanceStreamPace(pace, 0, FRAME_MS * 2), 0);
});

test("advanceStreamPace keeps making progress on a tiny backlog", () => {
  const pace = createStreamPace(0, 0);
  let length = 0;
  for (let now = FRAME_MS; now <= 3000 && length < 3; now += FRAME_MS) {
    length = advanceStreamPace(pace, 3, now);
  }
  assert.equal(length, 3, "a small backlog must fully drain");
});

test("advanceStreamPace caps the elapsed time per update", () => {
  const pace = createStreamPace(0, 0);
  advanceStreamPace(pace, 1000, FRAME_MS);
  // タブ非表示明けの巨大なdtでも残量を一気に流し込まない。
  // A huge dt (hidden tab) must not flush the whole backlog at once.
  const next = advanceStreamPace(pace, 1000, 10000);
  assert.ok(next < 1000, `a huge dt must not reveal everything (saw ${next})`);
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
