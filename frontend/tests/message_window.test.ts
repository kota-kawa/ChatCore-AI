import assert from "node:assert/strict";
import test from "node:test";

import {
  capUiChatMessages,
  prependUiChatMessagesWithinLimit,
  rememberStreamEventId,
} from "../lib/chat_page/message_window";
import type { UiChatMessage } from "../lib/chat_page/types";

function message(index: number): UiChatMessage {
  return {
    id: `message-${index}`,
    sender: index % 2 === 0 ? "user" : "assistant",
    text: `text-${index}`,
  };
}

test("capUiChatMessages keeps the newest messages", () => {
  const messages = Array.from({ length: 6 }, (_, index) => message(index));

  assert.deepEqual(
    capUiChatMessages(messages, 3).map((item) => item.id),
    ["message-3", "message-4", "message-5"],
  );
});

test("prependUiChatMessagesWithinLimit keeps a bounded loaded window", () => {
  const olderMessages = [message(0), message(1), message(2)];
  const currentMessages = [message(3), message(4), message(5)];

  assert.deepEqual(
    prependUiChatMessagesWithinLimit(olderMessages, currentMessages, 5).map((item) => item.id),
    ["message-1", "message-2", "message-3", "message-4", "message-5"],
  );
});

test("rememberStreamEventId rejects replayed event ids", () => {
  const lastEventIdByRoom = new Map<string, number>();

  assert.equal(rememberStreamEventId(lastEventIdByRoom, "room-a", 1), true);
  assert.equal(rememberStreamEventId(lastEventIdByRoom, "room-a", 1), false);
  assert.equal(rememberStreamEventId(lastEventIdByRoom, "room-a", 0), true);
  assert.equal(rememberStreamEventId(lastEventIdByRoom, "room-a", 2), true);
  assert.equal(lastEventIdByRoom.get("room-a"), 2);
});
