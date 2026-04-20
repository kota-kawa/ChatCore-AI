import type {
  ChatHistoryMessagePayload,
  ChatHistoryPagination,
  ChatRoom,
} from "./types";

type UnknownRecord = Record<string, unknown>;

function asRecord(value: unknown): UnknownRecord {
  if (!value || typeof value !== "object") return {};
  return value as UnknownRecord;
}

function asString(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  return value;
}

function asPositiveNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  if (value < 1) return null;
  return value;
}

export function normalizeChatRoom(raw: unknown): ChatRoom | null {
  const record = asRecord(raw);
  const rawId = record.id;
  if (rawId === undefined || rawId === null) return null;

  const rawTitle = asString(record.title);
  const rawCreatedAt = asString(record.created_at);
  const rawMode = asString(record.mode);

  return {
    id: String(rawId),
    title: rawTitle && rawTitle.trim() ? rawTitle : "新規チャット",
    createdAt: rawCreatedAt,
    mode: rawMode === "temporary" ? "temporary" : "normal",
  };
}

export function normalizeChatRooms(rawRooms: unknown): ChatRoom[] {
  if (!Array.isArray(rawRooms)) return [];
  return rawRooms
    .map((room) => normalizeChatRoom(room))
    .filter((room): room is ChatRoom => room !== null);
}

export function normalizeChatHistoryMessages(rawMessages: unknown): ChatHistoryMessagePayload[] {
  if (!Array.isArray(rawMessages)) return [];
  return rawMessages.map((entry) => {
    const record = asRecord(entry);
    return {
      id: asPositiveNumber(record.id) ?? undefined,
      message: asString(record.message),
      sender: asString(record.sender),
      timestamp: asString(record.timestamp),
    };
  });
}

export function normalizeChatHistoryPagination(rawPagination: unknown): ChatHistoryPagination {
  const pagination = asRecord(rawPagination);
  return {
    hasMore: pagination.has_more === true,
    nextBeforeId: asPositiveNumber(pagination.next_before_id),
  };
}
