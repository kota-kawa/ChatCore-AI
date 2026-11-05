// チャットAPIのZodスキーマと型の再エクスポート窓口。実体はバックエンドのスキーマから生成された generated/api_schemas にある。
// Re-export entry point for chat API Zod schemas and types; the definitions live in generated/api_schemas, produced from the backend schemas.
export {
  ApiErrorPayloadSchema,
  ChatJsonResponseSchema,
  ChatGenerationStatusResponseSchema,
  ChatHistoryMessageSchema,
  ChatHistoryPaginationSchema,
  ChatHistoryResponseSchema,
  ShareChatRoomResponseSchema,
  StoredChatHistoryEntrySchema
} from "./generated/api_schemas";
export type {
  ApiErrorPayload,
  ChatJsonResponse,
  ChatGenerationStatusResponse,
  ChatHistoryMessage,
  ChatHistoryPagination,
  ChatHistoryResponse,
  ShareChatRoomResponse,
  StoredChatHistoryEntry
} from "./generated/api_schemas";
