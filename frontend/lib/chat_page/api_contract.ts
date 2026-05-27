import type {
  ChatHistoryMessagePayload,
  ChatHistoryPagination,
  ChatResponsePayload,
  ChatMessagePart,
  ChatRoom,
  ChatRoomMode,
  ChatRoomsPage,
  ChatRoomsPagination,
  GenerativeUiArtifactV1,
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

function normalizeArtifact(raw: unknown): GenerativeUiArtifactV1 | null {
  const record = asRecord(raw);
  if (record.version !== 1) return null;
  const title = optionalString(record.title);
  const html = optionalString(record.html);
  const css = optionalString(record.css);
  const js = optionalString(record.js);
  if (!title || html === undefined || css === undefined || js === undefined) return null;

  const description = optionalString(record.description);
  const height =
    typeof record.height === "number" && Number.isFinite(record.height)
      ? Math.min(Math.max(Math.round(record.height), 160), 900)
      : undefined;

  return {
    version: 1,
    title,
    ...(description ? { description } : {}),
    ...(height ? { height } : {}),
    html,
    css,
    js,
  };
}

function normalizeMessageParts(rawParts: unknown): ChatMessagePart[] | undefined {
  if (!Array.isArray(rawParts)) return undefined;
  const parts: ChatMessagePart[] = [];
  rawParts.forEach((rawPart) => {
    const part = asRecord(rawPart);
    if (part.type === "text") {
      const text = optionalString(part.text);
      if (text !== undefined) parts.push({ type: "text", text });
      return;
    }
    if (part.type === "sandbox_artifact") {
      const artifact = normalizeArtifact(part.artifact);
      if (artifact) parts.push({ type: "sandbox_artifact", artifact });
    }
  });
  return parts.length > 0 ? parts : undefined;
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

export function normalizeChatRoomsPagination(rawPagination: unknown): ChatRoomsPagination {
  const pagination = asRecord(rawPagination);
  return {
    hasMore: pagination.has_more === true,
    nextCursor: optionalString(pagination.next_cursor) ?? null,
  };
}

export function normalizeChatRoomsPayload(rawPayload: unknown): ChatRoomsPage {
  const payload = asRecord(rawPayload);
  return {
    rooms: normalizeChatRooms(payload.rooms),
    pagination: normalizeChatRoomsPagination(payload.pagination),
    error: optionalString(payload.error),
  };
}

export function normalizeChatHistoryMessages(rawMessages: unknown): ChatHistoryMessagePayload[] {
  if (!Array.isArray(rawMessages)) return [];
  return rawMessages.map((entry) => {
    const record = asRecord(entry);
    const rawFileNames = record.attached_file_names;
    const attached_file_names =
      Array.isArray(rawFileNames) && rawFileNames.length > 0
        ? (rawFileNames.filter((n) => typeof n === "string") as string[])
        : undefined;
    const rawSiblingIds = record.sibling_ids;
    const sibling_ids = Array.isArray(rawSiblingIds)
      ? (rawSiblingIds.filter((value) => typeof value === "number") as number[])
      : undefined;
    const message_parts = normalizeMessageParts(record.message_parts);
    return {
      id: asPositiveNumber(record.id) ?? undefined,
      message: optionalString(record.message),
      sender: optionalString(record.sender),
      timestamp: optionalString(record.timestamp),
      ...(message_parts ? { message_parts } : {}),
      ...(attached_file_names ? { attached_file_names } : {}),
      ...(asPositiveNumber(record.version_index) ? { version_index: asPositiveNumber(record.version_index)! } : {}),
      ...(asPositiveNumber(record.version_count) ? { version_count: asPositiveNumber(record.version_count)! } : {}),
      ...(sibling_ids && sibling_ids.length > 0 ? { sibling_ids } : {}),
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

export function normalizeChatResponsePayload(rawPayload: unknown): ChatResponsePayload {
  const payload = asRecord(rawPayload);
  const parts = normalizeMessageParts(payload.parts);
  return {
    response: optionalString(payload.response),
    ...(parts ? { parts } : {}),
    error: optionalString(payload.error),
    roomTitle: optionalString(payload.room_title),
  };
}

export function normalizeShareChatRoomPayload(rawPayload: unknown): { shareUrl?: string } {
  const payload = asRecord(rawPayload);
  return {
    shareUrl: optionalString(payload.share_url),
  };
}
