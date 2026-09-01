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
