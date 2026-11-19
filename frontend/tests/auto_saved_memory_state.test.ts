// 「記憶しました」通知の状態（取得結果の合流、取り消し済みの保持、確定した回答の ID）を検証する。
// Tests the "remembered" notice state: merging fetches, keeping undone notices and finding the settled answer id.

import assert from "node:assert/strict";
import test from "node:test";

import {
  findLastAssistantServerId,
  markAutoSavedMemoryUndone,
  mergeAutoSavedMemories,
  NO_AUTO_SAVED_MEMORIES,
} from "../lib/chat_page/auto_saved_memory_state";
import type { UiChatMessage } from "../lib/chat_page/types";

const memory = (id: number, messageId: number, title = `T${id}`, revision = 1) => ({ id, messageId, title, revision });

test("mergeAutoSavedMemories groups notices by message and orders them by id", () => {
  const merged = mergeAutoSavedMemories(NO_AUTO_SAVED_MEMORIES, [memory(5, 10), memory(4, 10), memory(6, 11)]);
  assert.deepEqual(merged.get(10)?.map((entry) => entry.id), [4, 5]);
  assert.equal(merged.get(11)?.[0]?.status, "saved");
});

test("mergeAutoSavedMemories keeps the previous reference when nothing changed", () => {
  const first = mergeAutoSavedMemories(NO_AUTO_SAVED_MEMORIES, [memory(4, 10)]);
  assert.equal(mergeAutoSavedMemories(first, [memory(4, 10)]), first);
  assert.equal(mergeAutoSavedMemories(NO_AUTO_SAVED_MEMORIES, []), NO_AUTO_SAVED_MEMORIES);
});

test("an undone notice survives the next fetch even though the server no longer lists it", () => {
  const saved = mergeAutoSavedMemories(NO_AUTO_SAVED_MEMORIES, [memory(4, 10), memory(5, 10)]);
  const undone = markAutoSavedMemoryUndone(saved, { id: 4, messageId: 10 });
  assert.equal(undone.get(10)?.find((entry) => entry.id === 4)?.status, "undone");
  const refetched = mergeAutoSavedMemories(undone, [memory(5, 10)]);
  assert.deepEqual(refetched.get(10)?.map((entry) => [entry.id, entry.status]), [[4, "undone"], [5, "saved"]]);
  assert.equal(mergeAutoSavedMemories(refetched, [memory(5, 10)]), refetched);
});

test("markAutoSavedMemoryUndone ignores unknown or already undone notices", () => {
  const saved = mergeAutoSavedMemories(NO_AUTO_SAVED_MEMORIES, [memory(4, 10)]);
  assert.equal(markAutoSavedMemoryUndone(saved, { id: 99, messageId: 10 }), saved);
  const undone = markAutoSavedMemoryUndone(saved, { id: 4, messageId: 10 });
  assert.equal(markAutoSavedMemoryUndone(undone, { id: 4, messageId: 10 }), undone);
});

test("findLastAssistantServerId skips streaming, error and unsaved rows", () => {
  const messages: UiChatMessage[] = [
    { id: "a1", sender: "assistant", text: "old", serverId: 7 },
    { id: "u1", sender: "user", text: "q", serverId: 8 },
    { id: "a2", sender: "assistant", text: "err", error: true, serverId: 9 },
    { id: "a3", sender: "assistant", text: "streaming", streaming: true },
  ];
  assert.equal(findLastAssistantServerId(messages), 7);
  assert.equal(findLastAssistantServerId([...messages, { id: "a4", sender: "assistant", text: "new", serverId: 12 }]), 12);
  assert.equal(findLastAssistantServerId([]), null);
});
