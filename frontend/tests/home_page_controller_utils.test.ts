import assert from "node:assert/strict";
import test from "node:test";

import { CHAT_ROOMS_PAGE_SIZE } from "../lib/chat_page/constants";

import {
  buildTaskOrderForPersistence,
  isLatestChatTurnAnswered,
  limitToFirstChatRoomsPage,
  mergeUniqueChatRooms,
  moveChatRoomToFront,
  removeTaskById,
  removeChatRoomsById,
  setChatRoomPinnedAt,
  splitPinnedChatRooms,
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

test("splitPinnedChatRooms orders pins newest first and keeps the rest in list order", () => {
  const { pinned, recent } = splitPinnedChatRooms([
    { id: "r1", title: "R1", mode: "normal" },
    { id: "p-old", title: "Old pin", mode: "normal", pinnedAt: "2026-09-01T00:00:00" },
    { id: "r2", title: "R2", mode: "normal" },
    { id: "p-new", title: "New pin", mode: "normal", pinnedAt: "2026-09-20T00:00:00" },
  ]);

  assert.deepEqual(pinned.map((room) => room.id), ["p-new", "p-old"]);
  assert.deepEqual(recent.map((room) => room.id), ["r1", "r2"]);
});

test("setChatRoomPinnedAt pins in place and unpins back into activity order", () => {
  const rooms = [
    { id: "p", title: "P", mode: "normal" as const, lastActivityAt: "2026-09-12T00:00:00", pinnedAt: "2026-09-22T00:00:00" },
    { id: "a", title: "A", mode: "normal" as const, lastActivityAt: "2026-09-20T00:00:00" },
    { id: "b", title: "B", mode: "normal" as const, lastActivityAt: "2026-09-10T00:00:00" },
  ];

  const pinned = setChatRoomPinnedAt(rooms, "b", "2026-09-23T00:00:00");
  assert.deepEqual(pinned.map((room) => room.id), ["p", "a", "b"]);
  assert.equal(pinned[2]?.pinnedAt, "2026-09-23T00:00:00");

  const unpinned = setChatRoomPinnedAt(rooms, "p", null);
  assert.deepEqual(unpinned.map((room) => room.id), ["a", "p", "b"]);
  assert.equal("pinnedAt" in (unpinned[1] ?? {}), false);
});

test("setChatRoomPinnedAt appends an unpinned room older than every loaded room", () => {
  const rooms = [
    { id: "p", title: "P", mode: "normal" as const, lastActivityAt: "2026-01-01T00:00:00", pinnedAt: "2026-09-22T00:00:00" },
    { id: "a", title: "A", mode: "normal" as const, lastActivityAt: "2026-09-20T00:00:00" },
  ];

  assert.deepEqual(setChatRoomPinnedAt(rooms, "p", null).map((room) => room.id), ["a", "p"]);
  assert.equal(setChatRoomPinnedAt(rooms, "missing", null), rooms);
});

test("limitToFirstChatRoomsPage keeps every pin plus one page of the rest", () => {
  const pins = Array.from({ length: 3 }, (_, index) => ({
    id: `p${index}`,
    title: `P${index}`,
    mode: "normal" as const,
    pinnedAt: "2026-09-22T00:00:00",
  }));
  const recent = Array.from({ length: CHAT_ROOMS_PAGE_SIZE + 5 }, (_, index) => ({
    id: `r${index}`,
    title: `R${index}`,
    mode: "normal" as const,
  }));

  const limited = limitToFirstChatRoomsPage([...pins, ...recent]);

  assert.equal(limited.length, 3 + CHAT_ROOMS_PAGE_SIZE);
  assert.deepEqual(limited.slice(0, 3).map((room) => room.id), ["p0", "p1", "p2"]);
  assert.equal(limited.at(-1)?.id, `r${CHAT_ROOMS_PAGE_SIZE - 1}`);
});
