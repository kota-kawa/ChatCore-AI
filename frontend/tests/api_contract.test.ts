import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeChatResponsePayload,
  normalizeChatHistoryMessages,
  normalizeChatHistoryPagination,
  normalizeChatRoom,
  normalizeChatRooms,
  normalizeChatRoomsPayload,
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

test("normalizeChatRoomsPayload keeps room pagination", () => {
  const normalized = normalizeChatRoomsPayload({
    rooms: [{ id: "room-1", title: "Room 1", mode: "normal" }],
    pagination: {
      has_more: true,
      next_cursor: "cursor-20",
    },
  });

  assert.equal(normalized.rooms.length, 1);
  assert.deepEqual(normalized.pagination, {
    hasMore: true,
    nextCursor: "cursor-20",
  });
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

test("normalizeChatResponsePayload keeps generated room title", () => {
  const normalized = normalizeChatResponsePayload({
    response: "answer",
    room_title: "Thread title",
  });

  assert.deepEqual(normalized, {
    response: "answer",
    error: undefined,
    roomTitle: "Thread title",
  });
});

test("normalizers keep valid sandbox artifact parts", () => {
  const artifact = {
    version: 1,
    title: "Diagram",
    description: "Interactive view",
    height: 360,
    html: "<div></div>",
    css: "body{margin:0}",
    js: "document.body.textContent = 'ok';",
  };

  const history = normalizeChatHistoryMessages([
    {
      id: 6,
      message: "answer",
      sender: "assistant",
      message_parts: [
        { type: "text", text: "answer" },
        { type: "sandbox_artifact", artifact },
      ],
    },
  ]);
  assert.equal(history[0]?.message_parts?.[1]?.type, "sandbox_artifact");

  const response = normalizeChatResponsePayload({
    response: "answer",
    parts: [{ type: "sandbox_artifact", artifact }],
  });
  assert.equal(response.parts?.[0]?.type, "sandbox_artifact");
});

test("normalizers keep the three library declaration and drop unknown ones", () => {
  const artifact = {
    version: 1,
    title: "3D scene",
    height: 460,
    libraries: ["three", "react"],
    html: "<div id='app'></div>",
    css: "#app{height:420px}",
    js: "const scene = new THREE.Scene();",
  };

  const response = normalizeChatResponsePayload({
    response: "answer",
    parts: [{ type: "sandbox_artifact", artifact }],
  });

  const part = response.parts?.[0];
  assert.equal(part?.type, "sandbox_artifact");
  assert.deepEqual(
    part?.type === "sandbox_artifact" ? part.artifact.libraries : undefined,
    ["three"],
  );
});
