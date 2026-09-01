import assert from "node:assert/strict";
import test from "node:test";

import {
  buildTaskOrderForPersistence,
  isLatestChatTurnAnswered,
  mergeUniqueChatRooms,
  moveChatRoomToFront,
  removeTaskById,
  removeChatRoomsById,
  updateTaskById,
  updateChatRoomTitle,
} from "../lib/chat_page/home_page_controller_utils";

const duplicateNameTasks = [
  {
    task_id: 10,
    name: "同名タスク",
    prompt_template: "first",
    response_rules: "",
    output_skeleton: "",
    input_examples: "",
    output_examples: "",
    is_default: false,
  },
  {
    task_id: 11,
    name: "同名タスク",
    prompt_template: "second",
    response_rules: "",
    output_skeleton: "",
    input_examples: "",
    output_examples: "",
    is_default: false,
  },
];

test("removeTaskById removes only the selected row when names are duplicated", () => {
  assert.deepEqual(removeTaskById(duplicateNameTasks, 10).map((task) => task.task_id), [11]);
});

test("updateTaskById edits only the selected row when names are duplicated", () => {
  const updated = updateTaskById(duplicateNameTasks, 11, { name: "更新後" });
  assert.equal(updated[0]?.name, "同名タスク");
  assert.equal(updated[1]?.name, "更新後");
});

test("buildTaskOrderForPersistence returns stable task ids and ignores id-less fallback tasks", () => {
  const order = buildTaskOrderForPersistence([
    {
      task_id: null,
      name: "Default Task",
      prompt_template: "",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: true,
    },
    {
      task_id: 42,
      name: "  Create report  ",
      prompt_template: "",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: false,
    },
    {
      task_id: 43,
      name: "   ",
      prompt_template: "",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: false,
    },
    {
      task_id: 44,
      name: "Send summary",
      prompt_template: "",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: false,
    },
  ]);

  assert.deepEqual(order, [42, 43, 44]);
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

test("moveChatRoomToFront promotes an existing room without changing the others", () => {
  const rooms = [
    { id: "room-1", title: "Room 1", mode: "normal" as const },
    { id: "room-2", title: "Room 2", mode: "normal" as const },
    { id: "room-3", title: "Room 3", mode: "normal" as const },
  ];

  const promoted = moveChatRoomToFront(rooms, "room-3");

  assert.deepEqual(promoted.map((room) => room.id), ["room-3", "room-1", "room-2"]);
  assert.deepEqual(rooms.map((room) => room.id), ["room-1", "room-2", "room-3"]);
});

test("moveChatRoomToFront preserves the list when the room is absent", () => {
  const rooms = [{ id: "room-1", title: "Room 1", mode: "normal" as const }];
  assert.equal(moveChatRoomToFront(rooms, "missing"), rooms);
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
