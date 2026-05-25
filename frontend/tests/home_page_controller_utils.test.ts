import assert from "node:assert/strict";
import test from "node:test";

import {
  buildTaskOrderForPersistence,
  isLatestChatTurnAnswered,
  mergeUniqueChatRooms,
  removeChatRoomsById,
  updateChatRoomTitle,
} from "../lib/chat_page/home_page_controller_utils";

test("buildTaskOrderForPersistence excludes default tasks and empty names", () => {
  const order = buildTaskOrderForPersistence([
    {
      name: "Default Task",
      prompt_template: "",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: true,
    },
    {
      name: "  Create report  ",
      prompt_template: "",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: false,
    },
    {
      name: "   ",
      prompt_template: "",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: false,
    },
    {
      name: "Send summary",
      prompt_template: "",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: false,
    },
  ]);

  assert.deepEqual(order, ["Create report", "Send summary"]);
});

test("isLatestChatTurnAnswered is true when an assistant reply follows the latest user message", () => {
  assert.equal(
    isLatestChatTurnAnswered([
      { sender: "user" },
      { sender: "assistant" },
    ]),
    true,
  );
});

test("isLatestChatTurnAnswered is false when the latest user message is still pending", () => {
  assert.equal(
    isLatestChatTurnAnswered([
      { sender: "user" },
      { sender: "assistant" },
      { sender: "user" },
    ]),
    false,
  );
});

test("isLatestChatTurnAnswered ignores thinking placeholders", () => {
  assert.equal(
    isLatestChatTurnAnswered([
      { sender: "user" },
      { sender: "thinking" },
    ]),
    false,
  );
});

test("mergeUniqueChatRooms appends only unseen rooms", () => {
  const merged = mergeUniqueChatRooms(
    [
      { id: "room-1", title: "Room 1", mode: "normal" },
      { id: "room-2", title: "Room 2", mode: "normal" },
    ],
    [
      { id: "room-2", title: "Duplicate", mode: "normal" },
      { id: "room-3", title: "Room 3", mode: "normal" },
    ],
  );

  assert.deepEqual(
    merged.map((room) => room.id),
    ["room-1", "room-2", "room-3"],
  );
  assert.equal(merged[1]?.title, "Room 2");
});

test("removeChatRoomsById removes deleted room ids", () => {
  const rooms = removeChatRoomsById(
    [
      { id: "room-1", title: "Room 1", mode: "normal" },
      { id: "room-2", title: "Room 2", mode: "normal" },
      { id: "room-3", title: "Room 3", mode: "normal" },
    ],
    ["room-1", "room-3"],
  );

  assert.deepEqual(
    rooms.map((room) => room.id),
    ["room-2"],
  );
});

test("updateChatRoomTitle trims and updates only the matching room", () => {
  const rooms = updateChatRoomTitle(
    [
      { id: "room-1", title: "Room 1", mode: "normal" },
      { id: "room-2", title: "Room 2", mode: "normal" },
    ],
    "room-2",
    "  Renamed  ",
  );

  assert.equal(rooms[0]?.title, "Room 1");
  assert.equal(rooms[1]?.title, "Renamed");
});
