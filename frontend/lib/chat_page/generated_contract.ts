// 日本語: バックエンドの Pydantic モデルから生成された Zod スキーマ（`types/generated/api_schemas.ts`）で
//         チャット系ペイロードを検証する薄い橋渡し層です。契約が所有するフィールドの型検査を
//         手書きガードから生成物へ寄せ、バックエンドとフロントの契約ずれを検知できるようにします。
// English: Thin bridge that validates the chat payloads with the Zod schemas generated from the backend
//          Pydantic models (`types/generated/api_schemas.ts`). Type checking of the contract-owned fields
//          moves from hand-written guards to the generated artifact so backend/frontend drift is caught.
//
// 日本語: 生成スキーマは nullable だが型には厳格なので、`parse` は使わず必ず `safeParse` を使い、
//         失敗時は「未指定」を意味する null / 既定値へ落とします。これにより、これまでの
//         `lib/chat_page/api_contract.ts` の手書きガードと同じ寛容さ（型不一致は捨てる、例外は投げない）を保ちます。
// English: The generated schemas are nullable but type-strict, so we never call `parse` — always
//          `safeParse` — and fall back to null / the previous default on failure. That preserves the
//          leniency of the former hand-written guards in `lib/chat_page/api_contract.ts` (drop mismatched
//          values, never throw).
import { z } from "zod";

import {
  ChatGenerationStatusResponseSchema,
  ChatHistoryMessageSchema,
  ChatHistoryPaginationSchema,
  ChatHistoryResponseSchema,
  ChatJsonResponseSchema,
  ShareChatRoomResponseSchema,
} from "../../types/generated/api_schemas";
import { asRecord } from "../utils";
import type { ChatHistoryPagination, GenerationStatusPayload } from "./types";

// 日本語: 生成スキーマの 1 フィールドを検証し、失敗時は null を返す。
// English: Validate a single generated-schema field, returning null on failure.
function parseField<TSchema extends z.ZodTypeAny>(schema: TSchema, value: unknown): z.output<TSchema> | null {
  const parsed = schema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

// 日本語: 文字列フィールドを `string | undefined` に揃える（旧 `optionalString` と同一の挙動）。
// English: Reduce a string field to `string | undefined` (identical to the former `optionalString`).
function stringField(schema: z.ZodTypeAny, value: unknown): string | undefined {
  const parsed = parseField(schema, value);
  return typeof parsed === "string" ? parsed : undefined;
}

// 日本語: 真偽フィールドを厳密に `true` かどうかで畳む（旧 `asBoolean` と同一の挙動）。
// English: Fold a boolean field on a strict `true` comparison (identical to the former `asBoolean`).
function booleanField(schema: z.ZodTypeAny, value: unknown): boolean {
  return parseField(schema, value) === true;
}

// 日本語: 生成スキーマは ID を整数のみ許容するが、旧 `asPositiveNumber` は有限の非整数も通していた。
//         挙動を変えないため `z.number()`（zod v4 では NaN/Infinity を拒否）との union で寛容さを保ち、
//         そのうえでアプリ側の規則どおり 1 未満を「ID なし」として null に落とす。
// English: The generated schemas allow integers only, but the former `asPositiveNumber` also passed finite
//          non-integers through. To keep behaviour identical we compose a union with `z.number()` (which
//          rejects NaN/Infinity in zod v4) and then apply the app rule that anything below 1 means "no id".
function positiveIdField(schema: z.ZodTypeAny, value: unknown): number | null {
  const parsed = parseField(z.union([schema, z.number()]), value);
  if (typeof parsed !== "number") return null;
  return parsed < 1 ? null : parsed;
}

// 日本語: `ChatJsonResponse` が所有するフィールド（応答本文とエラー）を読み取る。
//         `parts` / `room_title` は Pydantic モデル未定義の追加キーなので、呼び出し側が生の値から読む。
// English: Read the fields owned by `ChatJsonResponse` (answer body and error). `parts` / `room_title` are
//          extra keys not declared on the Pydantic model, so the caller still reads them from the raw value.
export function readChatJsonResponseFields(raw: unknown): { response?: string; error?: string } {
  const record = asRecord(raw);
  const shape = ChatJsonResponseSchema.shape;
  return {
    response: stringField(shape.response, record.response),
    error: stringField(shape.error, record.error),
  };
}

// 日本語: `ChatGenerationStatusResponse` は生成状況ペイロードを完全に記述しているため全項目を読み取る。
// English: `ChatGenerationStatusResponse` fully describes the generation-status payload, so read every field.
export function readChatGenerationStatusFields(raw: unknown): GenerationStatusPayload {
  const record = asRecord(raw);
  const shape = ChatGenerationStatusResponseSchema.shape;
  return {
    error: stringField(shape.error, record.error),
    is_generating: booleanField(shape.is_generating, record.is_generating),
    has_replayable_job: booleanField(shape.has_replayable_job, record.has_replayable_job),
  };
}

// 日本語: `ChatHistoryMessage` が所有するフィールドを読み取る。`message_parts` /
//         `attached_file_names` / `version_index` / `version_count` / `sibling_ids` は
//         Pydantic モデル未定義の追加キーなので、呼び出し側が生の値から読む。
// English: Read the fields owned by `ChatHistoryMessage`. `message_parts`, `attached_file_names`,
//          `version_index`, `version_count`, and `sibling_ids` are extra keys not declared on the Pydantic
//          model, so the caller still reads them from the raw value.
export function readChatHistoryMessageFields(raw: unknown): {
  id?: number;
  message?: string;
  sender?: string;
  timestamp?: string;
} {
  const record = asRecord(raw);
  const shape = ChatHistoryMessageSchema.shape;
  return {
    id: positiveIdField(shape.id, record.id) ?? undefined,
    message: stringField(shape.message, record.message),
    sender: stringField(shape.sender, record.sender),
    timestamp: stringField(shape.timestamp, record.timestamp),
  };
}

// 日本語: `ChatHistoryPagination` は履歴ページネーションを完全に記述しているため全項目を読み取る。
//         `limit` はフロントで未使用のため公開しない。
// English: `ChatHistoryPagination` fully describes history pagination, so read every field we consume.
//          `limit` is unused on the frontend and therefore not surfaced.
export function readChatHistoryPaginationFields(raw: unknown): ChatHistoryPagination {
  const record = asRecord(raw);
  const shape = ChatHistoryPaginationSchema.shape;
  return {
    hasMore: booleanField(shape.has_more, record.has_more),
    nextBeforeId: positiveIdField(shape.next_before_id, record.next_before_id),
  };
}

// 日本語: `ChatHistoryResponse` が所有するエラー項目を読み取る。`messages` / `pagination` は
//         生成スキーマ側が要素まで厳格に検査してしまい 1 件の不正で全件落ちるため、
//         呼び出し側が 1 件ずつ `readChatHistoryMessageFields` に渡す。`room_mode` は追加キー。
// English: Read the error field owned by `ChatHistoryResponse`. `messages` / `pagination` are not parsed
//          wholesale because the generated schema validates array items strictly, so a single bad entry
//          would drop the whole page; the caller feeds entries through `readChatHistoryMessageFields`
//          one by one instead. `room_mode` is an extra key.
export function readChatHistoryResponseFields(raw: unknown): { error?: string } {
  const record = asRecord(raw);
  return { error: stringField(ChatHistoryResponseSchema.shape.error, record.error) };
}

// 日本語: `ShareChatRoomResponse` が所有する共有 URL を読み取る。
// English: Read the share URL owned by `ShareChatRoomResponse`.
export function readShareChatRoomResponseFields(raw: unknown): { shareUrl?: string } {
  const record = asRecord(raw);
  return { shareUrl: stringField(ShareChatRoomResponseSchema.shape.share_url, record.share_url) };
}
