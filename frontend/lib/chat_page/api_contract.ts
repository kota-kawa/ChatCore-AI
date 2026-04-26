import type {
  ChatHistoryMessagePayload,
  ChatHistoryPagination,
  ChatRoom,
  ChatRoomMode,
  GenerationStatusPayload,
} from "./types";

type UnknownRecord = Record<string, unknown>;

function isUnknownRecord(value: unknown): value is UnknownRecord {
  return Boolean(value) && typeof value === "object";
}

export function asRecord(value: unknown): UnknownRecord {
  return isUnknownRecord(value) ? value : {};
}

function optionalString(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  return value;
}

function asPositiveNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  if (value < 1) return null;
  return value;
}

function asBoolean(value: unknown): boolean {
  return value === true;
}

export function normalizeChatRoom(raw: unknown): ChatRoom | null {
  const record = asRecord(raw);
  const rawId = record.id;
  if (rawId === undefined || rawId === null) return null;

  const rawTitle = optionalString(record.title);
  const rawCreatedAt = optionalString(record.created_at);
  const rawMode = optionalString(record.mode);

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

export function normalizeChatRoomsPayload(rawPayload: unknown): { rooms: ChatRoom[]; error?: string } {
  const payload = asRecord(rawPayload);
  return {
    rooms: normalizeChatRooms(payload.rooms),
    error: optionalString(payload.error),
  };
}

export function normalizeChatHistoryMessages(rawMessages: unknown): ChatHistoryMessagePayload[] {
  if (!Array.isArray(rawMessages)) return [];
  return rawMessages.map((entry) => {
    const record = asRecord(entry);
    return {
      id: asPositiveNumber(record.id) ?? undefined,
      message: optionalString(record.message),
      sender: optionalString(record.sender),
      timestamp: optionalString(record.timestamp),
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

export function normalizeChatHistoryPayload(rawPayload: unknown): {
  error?: string;
  messages: ChatHistoryMessagePayload[];
  pagination: ChatHistoryPagination;
  roomMode: ChatRoomMode;
} {
  const payload = asRecord(rawPayload);
  return {
    error: optionalString(payload.error),
    messages: normalizeChatHistoryMessages(payload.messages),
    pagination: normalizeChatHistoryPagination(payload.pagination),
    roomMode: payload.room_mode === "temporary" ? "temporary" : "normal",
  };
}

export function normalizeGenerationStatusPayload(rawPayload: unknown): GenerationStatusPayload {
  const payload = asRecord(rawPayload);
  return {
    error: optionalString(payload.error),
    is_generating: asBoolean(payload.is_generating),
    has_replayable_job: asBoolean(payload.has_replayable_job),
  };
}

export function normalizeChatResponsePayload(rawPayload: unknown): { response?: string; error?: string } {
  const payload = asRecord(rawPayload);
  return {
    response: optionalString(payload.response),
    error: optionalString(payload.error),
  };
}

export function normalizeShareChatRoomPayload(rawPayload: unknown): { shareUrl?: string } {
  const payload = asRecord(rawPayload);
  return {
    shareUrl: optionalString(payload.share_url),
  };
}
