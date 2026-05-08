import assert from "node:assert/strict";
import test from "node:test";

import { createGenerationGuard } from "../lib/chat_page/generation_guard";

test("generation guard allows only one active generation at a time", () => {
  const guard = createGenerationGuard();
  const first = guard.acquire("room-a");

  assert.ok(first);
  assert.equal(first.roomId, "room-a");
  assert.equal(guard.acquire("room-b"), null);
  assert.equal(guard.isActive(first), true);
});

test("generation guard ignores stale releases after a newer generation starts", () => {
  const guard = createGenerationGuard();
  const first = guard.acquire("room-a");
  assert.ok(first);
  assert.equal(guard.abortActive(), first);
  assert.equal(first.abortController.signal.aborted, true);

  const second = guard.acquire("room-b");
  assert.ok(second);
  assert.equal(guard.release(first), false);
  assert.equal(guard.isActive(second), true);
  assert.equal(guard.release(second), true);
  assert.equal(guard.current(), null);
});
