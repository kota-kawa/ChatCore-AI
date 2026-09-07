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
  InteractiveButtonsV1,
  WebSearchImageV1,
  GenerationStatusPayload,
} from "./types";

import {
  readChatGenerationStatusFields,
  readChatHistoryMessageFields,
  readChatHistoryPaginationFields,
  readChatHistoryResponseFields,
  readChatJsonResponseFields,
  readShareChatRoomResponseFields,
} from "./generated_contract";
import { normalizeMessagePartsForDisplay } from "./message_parts_display";
import { asRecord } from "../utils";

function optionalString(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  return value;
}

// 日本語: バックエンドの Pydantic モデルに未定義な追加キー（`version_index` など）用の正の ID ガード。
//         契約が所有するフィールドは `generated_contract.ts` 側の生成スキーマで検証する。
// English: Positive-id guard for extra keys that are not declared on the backend Pydantic models
//          (`version_index` and friends). Contract-owned fields are validated by the generated schemas
//          in `generated_contract.ts` instead.
function asPositiveNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  if (value < 1) return null;
  return value;
}

// 日本語: 生成 UI アーティファクトはバックエンドの Pydantic レスポンスモデルに存在せず
//         （`services/generative_ui.py` が組み立てる追加キー）、生成 Zod スキーマの対応物がないため
//         手書きの正規化を残します。サンドボックス配信の制約（`libraries` の許可リスト、高さの上限）も
//         フロント固有の規則で、契約側には表現がありません。
// English: The generative-UI artifact has no counterpart among the generated Zod schemas because it is not
//          a backend Pydantic response model (it is an extra key assembled by `services/generative_ui.py`),
//          so the hand-written normalization stays. Its sandbox delivery rules (the `libraries` allow-list,
//          the height clamp) are frontend-only constraints with no representation in the contract either.
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
  const libraries = Array.isArray(record.libraries)
    ? record.libraries.filter((library): library is "three" => library === "three")
    : undefined;

  return {
    version: 1,
    title,
    ...(description ? { description } : {}),
    ...(height ? { height } : {}),
    ...(libraries && libraries.length > 0 ? { libraries } : {}),
    html,
    css,
    js,
  };
}

// 日本語: 対話ボタンもバックエンドの Pydantic レスポンスモデルではない追加キーのため、
//         生成 Zod スキーマの対応物がなく手書きの正規化を残します。
// English: Interactive buttons are likewise an extra key rather than a backend Pydantic response model, so
//          there is no generated Zod counterpart and the hand-written normalization stays.
function normalizeInteractiveButtons(rawButtons: unknown): InteractiveButtonsV1 | undefined {
  const record = asRecord(rawButtons);
  const type = optionalString(record.type);
  if (type !== "yes_no" && type !== "multiple_choice") return undefined;

  const question = optionalString(record.question);
  if (!question) return undefined;

  const rawOptions = record.options;
  const options =
    Array.isArray(rawOptions)
      ? (rawOptions.filter((o) => typeof o === "string").map((o) => o as string))
      : undefined;

  return {
    type,
    question,
    ...(options && options.length > 0 ? { options } : {}),
  };
}

// 日本語: Web 検索画像もバックエンドの Pydantic レスポンスモデルではない追加キーのため、
//         生成 Zod スキーマの対応物がありません。加えて http/https のみ許可する URL 検査は
//         フロント固有のセキュリティ規則なので、契約側へ移せません。
// English: Web-search images are also an extra key rather than a backend Pydantic response model, so there
//          is no generated Zod counterpart. The http/https-only URL check is additionally a frontend-only
//          security rule that cannot move into the contract.
function normalizeWebSearchImage(rawImage: unknown): WebSearchImageV1 | undefined {
  const record = asRecord(rawImage);
  const url = optionalString(record.url);
  const alt = optionalString(record.alt);
  const sourceUrl = optionalString(record.source_url);
  if (!url || !alt || !sourceUrl) return undefined;
  try {
    const imageUrl = new URL(url);
    const pageUrl = new URL(sourceUrl);
    if (!/^https?:$/.test(imageUrl.protocol) || !/^https?:$/.test(pageUrl.protocol)) return undefined;
  } catch {
    return undefined;
  }
  const sourceTitle = optionalString(record.source_title);
  return {
    url,
    alt,
    sourceUrl,
    ...(sourceTitle ? { sourceTitle } : {}),
  };
}

// 日本語: `message_parts` / `parts` はバックエンドの Pydantic レスポンスモデル
//         （`ChatHistoryMessage` / `ChatJsonResponse`）に宣言されていない追加キーで、
//         生成 Zod スキーマの対応物がありません。表示順の並べ替えもフロント固有です。
// English: `message_parts` / `parts` are extra keys not declared on the backend Pydantic response models
//          (`ChatHistoryMessage` / `ChatJsonResponse`), so no generated Zod schema describes them. The
//          display reordering is frontend-only as well.
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
      return;
    }
    if (part.type === "interactive_buttons") {
      const buttons = normalizeInteractiveButtons(part.buttons);
      if (buttons) parts.push({ type: "interactive_buttons", buttons });
      return;
    }
    if (part.type === "web_search_image") {
      const image = normalizeWebSearchImage(part.image);
      if (image) parts.push({ type: "web_search_image", image });
      return;
    }
  });
  const orderedParts = normalizeMessagePartsForDisplay(parts);
  return orderedParts.length > 0 ? orderedParts : undefined;
}

// 日本語: チャットルーム一覧はバックエンドが Pydantic モデルを介さず dict を直接返している
//         （`blueprints/chat/rooms.py` の `{"rooms": ..., "pagination": ...}`）ため、対応する生成 Zod
//         スキーマがありません。既定タイトルを共有する `NewChatRoomRequestSchema` はリクエスト契約で、
//         レスポンスには存在しない `id` 必須／`created_at` 未定義といった差があるため流用できません。
//         レスポンス用の Pydantic モデルが追加されたら、この正規化を生成スキーマへ置き換えてください。
// English: The chat-room list is returned by the backend as a plain dict without a Pydantic model
//          (`{"rooms": ..., "pagination": ...}` in `blueprints/chat/rooms.py`), so no generated Zod schema
//          corresponds to it. `NewChatRoomRequestSchema`, which shares the default title, is a *request*
//          contract and cannot be reused: it requires `id` and does not declare `created_at`, unlike the
//          response. Replace this normalization with a generated schema once a response model is added.
export function normalizeChatRoom(raw: unknown): ChatRoom | null {
  const record = asRecord(raw);
  const rawId = record.id;
  if (rawId === undefined || rawId === null) return null;

  const rawTitle = optionalString(record.title);
  const rawCreatedAt = optionalString(record.created_at);
  const rawLastActivityAt = optionalString(record.last_activity_at);
  const rawMode = optionalString(record.mode);

  return {
    id: String(rawId),
    title: rawTitle && rawTitle.trim() ? rawTitle : "新規チャット",
    createdAt: rawCreatedAt,
    ...(rawLastActivityAt !== undefined ? { lastActivityAt: rawLastActivityAt } : {}),
    mode: rawMode === "temporary" ? "temporary" : "normal",
  };
}

export function normalizeChatRooms(rawRooms: unknown): ChatRoom[] {
  if (!Array.isArray(rawRooms)) return [];
  return rawRooms
    .map((room) => normalizeChatRoom(room))
    .filter((room): room is ChatRoom => room !== null);
}

// 日本語: ルーム一覧のページネーション（`has_more` / `next_cursor`）にも生成 Zod スキーマの対応物が
//         ありません。`ChatHistoryPaginationSchema` は `next_before_id` を持つ別形状です。
// English: The room-list pagination (`has_more` / `next_cursor`) has no generated Zod counterpart either.
//          `ChatHistoryPaginationSchema` is a different shape built around `next_before_id`.
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

// 日本語: `id` / `message` / `sender` / `timestamp` は生成スキーマ `ChatHistoryMessageSchema` で検証し、
//         契約に宣言のない追加キーだけをここで正規化します。
// English: `id`, `message`, `sender`, and `timestamp` are validated by the generated
//          `ChatHistoryMessageSchema`; only the extra keys absent from the contract are normalized here.
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
      ...readChatHistoryMessageFields(record),
      ...(message_parts ? { message_parts } : {}),
      ...(attached_file_names ? { attached_file_names } : {}),
      ...(asPositiveNumber(record.version_index) ? { version_index: asPositiveNumber(record.version_index)! } : {}),
      ...(asPositiveNumber(record.version_count) ? { version_count: asPositiveNumber(record.version_count)! } : {}),
      ...(sibling_ids && sibling_ids.length > 0 ? { sibling_ids } : {}),
    };
  });
}

export function normalizeChatHistoryPagination(rawPagination: unknown): ChatHistoryPagination {
  return readChatHistoryPaginationFields(rawPagination);
}

// 日本語: `error` は生成スキーマ `ChatHistoryResponseSchema` で検証します。`room_mode` は
//         バックエンドが Pydantic モデル外で付与する追加キー（`blueprints/chat/messages.py`）なので、
//         生成スキーマに現れず手書きの既定値処理を残します。
// English: `error` is validated by the generated `ChatHistoryResponseSchema`. `room_mode` is an extra key
//          the backend attaches outside the Pydantic model (`blueprints/chat/messages.py`), so it does not
//          appear in the generated schema and keeps its hand-written defaulting.
export function normalizeChatHistoryPayload(rawPayload: unknown): {
  error?: string;
  messages: ChatHistoryMessagePayload[];
  pagination: ChatHistoryPagination;
  roomMode: ChatRoomMode;
} {
  const payload = asRecord(rawPayload);
  return {
    ...readChatHistoryResponseFields(payload),
    messages: normalizeChatHistoryMessages(payload.messages),
    pagination: normalizeChatHistoryPagination(payload.pagination),
    roomMode: payload.room_mode === "temporary" ? "temporary" : "normal",
  };
}

export function normalizeGenerationStatusPayload(rawPayload: unknown): GenerationStatusPayload {
  return readChatGenerationStatusFields(rawPayload);
}

// 日本語: `response` / `error` は生成スキーマ `ChatJsonResponseSchema` で検証します。`parts` と
//         `room_title` は `services/chat_use_case.py` が Pydantic モデル外で付与する追加キーのため、
//         生成スキーマに現れず手書きの正規化を残します。
// English: `response` / `error` are validated by the generated `ChatJsonResponseSchema`. `parts` and
//          `room_title` are extra keys attached by `services/chat_use_case.py` outside the Pydantic model,
//          so they do not appear in the generated schema and keep their hand-written normalization.
export function normalizeChatResponsePayload(rawPayload: unknown): ChatResponsePayload {
  const payload = asRecord(rawPayload);
  const parts = normalizeMessageParts(payload.parts);
  const { response, error } = readChatJsonResponseFields(payload);
  return {
    response,
    ...(parts ? { parts } : {}),
    error,
    roomTitle: optionalString(payload.room_title),
  };
}

export function normalizeShareChatRoomPayload(rawPayload: unknown): { shareUrl?: string } {
  return readShareChatRoomResponseFields(rawPayload);
}
