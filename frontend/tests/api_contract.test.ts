import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeChatHistoryMessages,
  normalizeChatHistoryPagination,
  normalizeChatRoom,
  normalizeChatRooms,
} from "../lib/chat_page/api_contract";

test("normalizeChatRoom normalizes incomplete payloads", () => {
  const normalized = normalizeChatRoom({
    id: 123,
    title: "   ",
    mode: "temporary",
    created_at: "2026-01-01T00:00:00Z",
  });

  assert.deepEqual(normalized, {
    id: "123",
    title: "新規チャット",
    mode: "temporary",
    createdAt: "2026-01-01T00:00:00Z",
  });
});

test("normalizeChatRooms drops invalid room entries", () => {
  const normalized = normalizeChatRooms([
    { id: "room-1", title: "Room 1", mode: "normal" },
    null,
    { title: "missing-id" },
  ]);

  assert.equal(normalized.length, 1);
  assert.equal(normalized[0]?.id, "room-1");
});

test("normalizeChatHistoryMessages keeps known fields only", () => {
  const normalized = normalizeChatHistoryMessages([
    { id: 5, message: "hello", sender: "user", timestamp: "2026-01-01" },
    { id: 0, message: null, sender: 3, timestamp: [] },
  ]);

  assert.deepEqual(normalized, [
    { id: 5, message: "hello", sender: "user", timestamp: "2026-01-01" },
    { id: undefined, message: undefined, sender: undefined, timestamp: undefined },
  ]);
});

test("normalizeChatHistoryPagination validates numeric boundaries", () => {
  const normalized = normalizeChatHistoryPagination({
    has_more: true,
    next_before_id: -10,
  });

  assert.deepEqual(normalized, {
    hasMore: true,
    nextBeforeId: null,
  });
});
