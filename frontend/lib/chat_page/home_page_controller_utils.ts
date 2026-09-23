import { CHAT_ROOMS_PAGE_SIZE } from "./constants";
import type { ChatRoom, NormalizedTask, UiChatMessage } from "./types";

export function removeTaskById(tasks: NormalizedTask[], taskId: number) {
  return tasks.filter((task) => task.task_id !== taskId);
}

export function updateTaskById(
  tasks: NormalizedTask[],
  taskId: number,
  updates: Partial<Omit<NormalizedTask, "task_id">>,
) {
  return tasks.map((task) => task.task_id === taskId ? { ...task, ...updates } : task);
}

export function buildTaskOrderForPersistence(tasks: NormalizedTask[]) {
  return tasks
    .map((task) => task.task_id)
    .filter((taskId): taskId is number => taskId !== null);
}

// 「思考中」プレースホルダーを取り除く。確定メッセージを積む直前に必ず通す。
// Drop the "thinking" placeholder; always applied right before a settled
// message is appended.
export function removeThinkingMessages(messages: UiChatMessage[]): UiChatMessage[] {
  return messages.filter((message) => message.sender !== "thinking");
}

export function isLatestChatTurnAnswered(messages: Pick<UiChatMessage, "sender">[]) {
  let latestUserIndex = -1;
  let latestAssistantIndex = -1;

  messages.forEach((message, index) => {
    if (message.sender === "user") {
      latestUserIndex = index;
      return;
    }

    if (message.sender === "assistant") {
      latestAssistantIndex = index;
    }
  });

  if (latestUserIndex === -1) {
    return latestAssistantIndex >= 0;
  }

  return latestAssistantIndex > latestUserIndex;
}

export function mergeUniqueChatRooms(primary: ChatRoom[], secondary: ChatRoom[]): ChatRoom[] {
  const seen = new Set<string>();
  const merged: ChatRoom[] = [];
  [...primary, ...secondary].forEach((room) => {
    if (seen.has(room.id)) return;
    seen.add(room.id);
    merged.push(room);
  });
  return merged;
}

export function removeChatRoomsById(rooms: ChatRoom[], roomIds: Iterable<string>): ChatRoom[] {
  const removed = new Set(roomIds);
  if (removed.size === 0) return rooms;
  return rooms.filter((room) => !removed.has(room.id));
}

export function moveChatRoomToFront(rooms: ChatRoom[], roomId: string): ChatRoom[] {
  const roomIndex = rooms.findIndex((room) => room.id === roomId);
  if (roomIndex <= 0) return rooms;
  return [rooms[roomIndex], ...rooms.slice(0, roomIndex), ...rooms.slice(roomIndex + 1)];
}

export function updateChatRoomTitle(rooms: ChatRoom[], roomId: string, title: string): ChatRoom[] {
  const normalizedTitle = title.trim();
  if (!normalizedTitle) return rooms;
  return rooms.map((room) =>
    room.id === roomId
      ? {
          ...room,
          title: normalizedTitle,
        }
      : room,
  );
}

function roomTimeValue(value: string | undefined): number {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
}

// サイドバーの2区画に振り分ける。ピン留めはピン留めした新しい順、残りは一覧の並び（最終アクティビティ順）を保つ。
// Split the sidebar into its two sections: pins newest-pin first, the rest in list order (latest activity first).
export function splitPinnedChatRooms(rooms: ChatRoom[]): { pinned: ChatRoom[]; recent: ChatRoom[] } {
  const pinned: ChatRoom[] = [];
  const recent: ChatRoom[] = [];
  rooms.forEach((room) => {
    (room.pinnedAt ? pinned : recent).push(room);
  });
  pinned.sort((a, b) => roomTimeValue(b.pinnedAt) - roomTimeValue(a.pinnedAt));
  return { pinned, recent };
}

// ピン留めを付け外しする。外したルームは最終アクティビティの位置へ戻し、ピン留め前の並びに合わせる。
// Pin or unpin a room. An unpinned room goes back to its latest-activity position among the unpinned rooms.
export function setChatRoomPinnedAt(rooms: ChatRoom[], roomId: string, pinnedAt: string | null): ChatRoom[] {
  const target = rooms.find((room) => room.id === roomId);
  if (!target) return rooms;
  if (pinnedAt) {
    return rooms.map((room) => (room.id === roomId ? { ...room, pinnedAt } : room));
  }

  const unpinned: ChatRoom = { ...target };
  delete unpinned.pinnedAt;
  const others = rooms.filter((room) => room.id !== roomId);
  const targetTime = roomTimeValue(unpinned.lastActivityAt);
  const insertAt = others.findIndex((room) => !room.pinnedAt && roomTimeValue(room.lastActivityAt) < targetTime);
  if (insertAt === -1) return [...others, unpinned];
  return [...others.slice(0, insertAt), unpinned, ...others.slice(insertAt)];
}

// SWR の最初のページとして持つ分に絞る。ピン留めはページングの外なので全件残し、残りだけを1ページ分に切る。
// Trim to what the cached first page holds: every pin (they sit outside pagination) plus one page of the rest.
export function limitToFirstChatRoomsPage(rooms: ChatRoom[]): ChatRoom[] {
  let unpinnedCount = 0;
  return rooms.filter((room) => {
    if (room.pinnedAt) return true;
    unpinnedCount += 1;
    return unpinnedCount <= CHAT_ROOMS_PAGE_SIZE;
  });
}
