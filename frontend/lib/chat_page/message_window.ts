import { MAX_RENDERED_CHAT_MESSAGES } from "./constants";
import type { UiChatMessage } from "./types";

export function capUiChatMessages(
  messages: UiChatMessage[],
  maxMessages = MAX_RENDERED_CHAT_MESSAGES,
): UiChatMessage[] {
  if (messages.length <= maxMessages) return messages;
  return messages.slice(messages.length - maxMessages);
}

export function prependUiChatMessagesWithinLimit(
  olderMessages: UiChatMessage[],
  currentMessages: UiChatMessage[],
  maxMessages = MAX_RENDERED_CHAT_MESSAGES,
): UiChatMessage[] {
  const currentWindow = capUiChatMessages(currentMessages, maxMessages);
  const availableOlderSlots = maxMessages - currentWindow.length;
  if (availableOlderSlots <= 0) return currentWindow;

  return [
    ...olderMessages.slice(Math.max(0, olderMessages.length - availableOlderSlots)),
    ...currentWindow,
  ];
}

export function rememberStreamEventId(
  lastEventIdByRoom: Map<string, number>,
  roomId: string,
  eventId: number | undefined,
) {
  if (typeof eventId !== "number" || eventId <= 0) return true;

  const lastEventId = lastEventIdByRoom.get(roomId) ?? 0;
  if (eventId <= lastEventId) return false;

  lastEventIdByRoom.set(roomId, eventId);
  return true;
}
