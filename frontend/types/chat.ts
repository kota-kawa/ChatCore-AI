import { z } from "zod";

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

const ApiDetailObjectSchema = z.object({
  msg: z.string().optional()
}).passthrough();

const ApiDetailSchema = z.union([
  z.string(),
  z.array(z.union([z.string(), ApiDetailObjectSchema]))
]);

export const ApiErrorPayloadSchema = z.object({
  error: z.string().optional(),
  message: z.string().optional(),
  detail: ApiDetailSchema.optional()
}).passthrough();

export type ApiErrorPayload = z.infer<typeof ApiErrorPayloadSchema>;

export const StreamEventDataSchema = z.record(z.unknown());

export const ChatJsonResponseSchema = ApiErrorPayloadSchema.extend({
  response: z.string().optional()
});

export type ChatJsonResponse = z.infer<typeof ChatJsonResponseSchema>;

export const ChatGenerationStatusResponseSchema = ApiErrorPayloadSchema.extend({
  is_generating: z.boolean().optional(),
  has_replayable_job: z.boolean().optional()
});

export type ChatGenerationStatusResponse = z.infer<typeof ChatGenerationStatusResponseSchema>;

export const ChatHistoryMessageSchema = z.object({
  id: z.number().optional(),
  message: z.string().optional(),
  sender: z.string().optional(),
  timestamp: z.string().optional()
}).passthrough();

export type ChatHistoryMessage = z.infer<typeof ChatHistoryMessageSchema>;

export const ChatHistoryPaginationSchema = z.object({
  has_more: z.boolean().optional(),
  next_before_id: z.number().nullable().optional(),
  limit: z.number().optional()
}).passthrough();

export type ChatHistoryPagination = z.infer<typeof ChatHistoryPaginationSchema>;

export const ChatHistoryResponseSchema = ApiErrorPayloadSchema.extend({
  messages: z.array(ChatHistoryMessageSchema).optional(),
  pagination: ChatHistoryPaginationSchema.optional()
});

export type ChatHistoryResponse = z.infer<typeof ChatHistoryResponseSchema>;

export const ShareChatRoomResponseSchema = ApiErrorPayloadSchema.extend({
  share_url: z.string().optional()
});

export type ShareChatRoomResponse = z.infer<typeof ShareChatRoomResponseSchema>;

export const StoredChatHistoryEntrySchema = z.object({
  text: z.string().optional(),
  sender: z.string().optional()
}).passthrough();

export type StoredChatHistoryEntry = z.infer<typeof StoredChatHistoryEntrySchema>;
