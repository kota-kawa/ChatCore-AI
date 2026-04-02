import { z } from "zod";

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

export type StreamingBotMessageHandle = {
  appendChunk: (chunk: string) => void;
  complete: () => void;
  showError: (message: string) => void;
};

export type DisplayMessageOptions = {
  prepend?: boolean;
  autoScroll?: boolean;
};

export type StreamEventPayload = {
  event: string;
  data: Record<string, unknown>;
  id?: number;
};

export const StreamEventDataSchema = z.record(z.unknown());
