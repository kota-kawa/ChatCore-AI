// チャットの「記憶しました」通知の状態を組み立てる純粋関数。取得結果の合流、取り消し済みの記録、
// 最新の回答のサーバー ID の取り出しを持つ。hooks/chat_page/use_auto_saved_memories.ts から使われる。
// Pure helpers for the chat's "remembered" notice state: merging fetch results, recording undone memories
// and finding the latest answer's server id. Used by hooks/chat_page/use_auto_saved_memories.ts.

import type { AutoSavedMemory } from "./auto_saved_memory_api";
import type { UiChatMessage } from "./types";

// 通知 1 件の表示状態。取り消すと undone になり、サーバーの一覧（有効な事実だけ）からは消えるので、
// 画面側が覚えておく。
// Display state of one notice. After an undo it becomes "undone"; the server list holds active facts only,
// so the screen has to remember it.
export type AutoSavedMemoryEntry = AutoSavedMemory & { status: "saved" | "undone" };

// メッセージ ID ごとの通知。変わらないあいだは同じ参照を返し、無関係な再描画を起こさない。
// Notices keyed by message id. The same reference is kept while nothing changes, so no unrelated re-render happens.
export type AutoSavedMemoriesByMessage = ReadonlyMap<number, readonly AutoSavedMemoryEntry[]>;

export const NO_AUTO_SAVED_MEMORIES: AutoSavedMemoriesByMessage = new Map();

function sameEntries(
  left: AutoSavedMemoriesByMessage,
  right: AutoSavedMemoriesByMessage,
): boolean {
  if (left.size !== right.size) return false;
  for (const [messageId, leftEntries] of left) {
    const rightEntries = right.get(messageId);
    if (!rightEntries || rightEntries.length !== leftEntries.length) return false;
    for (let index = 0; index < leftEntries.length; index += 1) {
      const a = leftEntries[index];
      const b = rightEntries[index];
      if (a.id !== b.id || a.status !== b.status || a.title !== b.title || a.revision !== b.revision) return false;
    }
  }
  return true;
}

// 取得結果を前の状態へ合流する。サーバーは有効な事実だけを返すので、取り消し済みの通知は前の状態から残す。
// 結果が前と同じなら前の参照をそのまま返す。
// Merge a fetch result into the previous state. The server returns active facts only, so undone notices are
// carried over from the previous state. An identical result returns the previous reference.
export function mergeAutoSavedMemories(
  previous: AutoSavedMemoriesByMessage,
  fetched: readonly AutoSavedMemory[],
): AutoSavedMemoriesByMessage {
  const grouped = new Map<number, AutoSavedMemoryEntry[]>();
  const add = (entry: AutoSavedMemoryEntry) => {
    const group = grouped.get(entry.messageId);
    if (group) group.push(entry);
    else grouped.set(entry.messageId, [entry]);
  };
  const fetchedIds = new Set(fetched.map((memory) => memory.id));
  for (const memory of fetched) add({ ...memory, status: "saved" });
  for (const entries of previous.values()) {
    for (const entry of entries) {
      if (entry.status === "undone" && !fetchedIds.has(entry.id)) add(entry);
    }
  }
  for (const group of grouped.values()) group.sort((a, b) => a.id - b.id);
  return sameEntries(previous, grouped) ? previous : grouped;
}

// 指定した通知を取り消し済みにする。対象が無ければ前の参照を返す。
// Mark one notice as undone; returns the previous reference when it is not present.
export function markAutoSavedMemoryUndone(
  previous: AutoSavedMemoriesByMessage,
  memory: Pick<AutoSavedMemory, "id" | "messageId">,
): AutoSavedMemoriesByMessage {
  const entries = previous.get(memory.messageId);
  if (!entries?.some((entry) => entry.id === memory.id && entry.status !== "undone")) return previous;
  const next = new Map(previous);
  next.set(
    memory.messageId,
    entries.map((entry) => (entry.id === memory.id ? { ...entry, status: "undone" as const } : entry)),
  );
  return next;
}

// 完了した最新の回答（エラー表示ではないもの）のサーバー ID。保存されていなければ null。
// 回答が確定したかどうかの目印にする。
// The server id of the latest completed answer (not an error row); null when none is persisted.
// Used as the marker that an answer has been finalized.
export function findLastAssistantServerId(messages: readonly UiChatMessage[]): number | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.sender === "assistant" && !message.error && !message.streaming && message.serverId !== undefined) {
      return message.serverId;
    }
  }
  return null;
}
