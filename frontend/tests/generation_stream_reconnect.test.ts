import assert from "node:assert/strict";
import test from "node:test";

import {
  GENERATION_STREAM_RECONNECT_DELAYS_MS,
  createAbortError,
  isUnrecoverableStreamStatus,
  waitForDuration,
  waitForGenerationStreamReconnect,
  waitUntilOnline,
} from "../lib/chat_page/generation_stream_reconnect";
import { createFakeClock, flushMicrotasks } from "./generation_stream_test_harness";

test("the reconnect backoff reconnects immediately once, then backs off up to a cap", () => {
  assert.deepEqual(GENERATION_STREAM_RECONNECT_DELAYS_MS, [0, 500, 1_000, 2_000, 4_000, 8_000, 15_000]);
});

test("waitForGenerationStreamReconnect walks the backoff table and holds at the cap", async () => {
  const clock = createFakeClock();
  const controller = new AbortController();

  for (let attempt = 0; attempt < 9; attempt += 1) {
    const waiting = waitForGenerationStreamReconnect(attempt, controller.signal, clock.reconnectRuntime);
    await flushMicrotasks();
    clock.advance(20_000);
    await waiting;
  }

  assert.deepEqual(clock.recordedDelays, [0, 500, 1_000, 2_000, 4_000, 8_000, 15_000, 15_000, 15_000]);
});

test("waitForDuration resolves only after the delay has elapsed", async () => {
  const clock = createFakeClock();
  const controller = new AbortController();
  let resolved = false;

  const waiting = waitForDuration(500, controller.signal, clock.reconnectRuntime).then(() => {
    resolved = true;
  });

  await flushMicrotasks();
  clock.advance(499);
  await flushMicrotasks();
  assert.equal(resolved, false);

  clock.advance(1);
  await waiting;
  assert.equal(resolved, true);
});

test("waitForDuration rejects at once when the signal is already aborted", async () => {
  const clock = createFakeClock();
  const controller = new AbortController();
  controller.abort();

  await assert.rejects(() => waitForDuration(500, controller.signal, clock.reconnectRuntime), {
    name: "AbortError",
  });
  assert.deepEqual(clock.recordedDelays, []);
});

test("aborting while waiting cancels the pending timer and rejects", async () => {
  const clock = createFakeClock();
  const controller = new AbortController();

  const waiting = waitForDuration(4_000, controller.signal, clock.reconnectRuntime);
  await flushMicrotasks();
  controller.abort();

  await assert.rejects(() => waiting, { name: "AbortError" });

  // タイマーが解除済みなら、時間を進めても何も起きない。
  // With the timer cleared, advancing time must do nothing.
  clock.advance(10_000);
});

test("createAbortError reuses an Error the caller attached as the abort reason", () => {
  const controller = new AbortController();
  const reason = new Error("ユーザーが停止しました");
  controller.abort(reason);

  assert.equal(createAbortError(controller.signal), reason);

  const plain = new AbortController();
  plain.abort();
  const fallback = createAbortError(plain.signal);
  assert.equal(fallback.name, "AbortError");
});

// オフラインの間は待ち続け、online で再開する。時間を進めても抜けない。
// While offline it keeps waiting and only resumes on "online"; advancing time
// alone must not release it.
test("waitUntilOnline blocks while offline and resumes on the online event", async () => {
  const clock = createFakeClock();
  clock.setOffline(true);
  const controller = new AbortController();
  let resolved = false;

  const waiting = waitUntilOnline(controller.signal, clock.reconnectRuntime).then(() => {
    resolved = true;
  });

  await flushMicrotasks();
  clock.advance(60_000);
  await flushMicrotasks();
  assert.equal(resolved, false);

  clock.goOnline();
  await waiting;
  assert.equal(resolved, true);
});

test("waitUntilOnline returns immediately when the browser reports online", async () => {
  const clock = createFakeClock();
  const controller = new AbortController();

  await waitUntilOnline(controller.signal, clock.reconnectRuntime);
  assert.deepEqual(clock.recordedDelays, []);
});

test("aborting an offline wait rejects instead of hanging", async () => {
  const clock = createFakeClock();
  clock.setOffline(true);
  const controller = new AbortController();

  const waiting = waitUntilOnline(controller.signal, clock.reconnectRuntime);
  await flushMicrotasks();
  controller.abort();

  await assert.rejects(() => waiting, { name: "AbortError" });
});

// 4xx は再接続で復旧しない（408 と 429 は一時的なので再試行できる）。
// A 4xx cannot be recovered by reconnecting; 408 and 429 are transient.
test("isUnrecoverableStreamStatus separates permanent failures from retryable ones", () => {
  assert.equal(isUnrecoverableStreamStatus(400), true);
  assert.equal(isUnrecoverableStreamStatus(401), true);
  assert.equal(isUnrecoverableStreamStatus(404), true);
  assert.equal(isUnrecoverableStreamStatus(408), false);
  assert.equal(isUnrecoverableStreamStatus(429), false);
  assert.equal(isUnrecoverableStreamStatus(500), false);
  assert.equal(isUnrecoverableStreamStatus(503), false);
  assert.equal(isUnrecoverableStreamStatus(200), false);
});
