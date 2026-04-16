// AUTO-GENERATED FILE. DO NOT EDIT MANUALLY.
// Source of truth: backend Pydantic models in services/request_models.py and services/response_models.py
// Regenerate with: python3 scripts/generate_frontend_zod_schemas.py
// Schema fingerprint: 34909dabeb414339e6ad20319bd7977c0c82ee875292b9c853259ea30ee77f85

import { z } from "zod";

export const EmailRequestSchema = z.object({ "email": z.string().min(1) });
export type EmailRequest = z.infer<typeof EmailRequestSchema>;

export const AuthCodeRequestSchema = z.object({ "authCode": z.union([z.string(), z.null()]).default(null) });
export type AuthCodeRequest = z.infer<typeof AuthCodeRequestSchema>;

export const NewChatRoomRequestSchema = z.object({ "id": z.string(), "title": z.string().default("新規チャット") });
export type NewChatRoomRequest = z.infer<typeof NewChatRoomRequestSchema>;

export const ChatRoomIdRequestSchema = z.object({ "room_id": z.string().min(1).max(128) });
export type ChatRoomIdRequest = z.infer<typeof ChatRoomIdRequestSchema>;

export const RenameChatRoomRequestSchema = z.object({ "room_id": z.string().min(1).max(128), "new_title": z.string().min(1) });
export type RenameChatRoomRequest = z.infer<typeof RenameChatRoomRequestSchema>;

export const ShareChatRoomRequestSchema = z.object({ "room_id": z.string().min(1).max(128) });
export type ShareChatRoomRequest = z.infer<typeof ShareChatRoomRequestSchema>;

export const ChatMessageRequestSchema = z.object({ "message": z.string().min(1).max(35000), "chat_room_id": z.string().min(1).max(128).default("default"), "model": z.union([z.string().min(1).max(64), z.null()]).default(null) });
export type ChatMessageRequest = z.infer<typeof ChatMessageRequestSchema>;

export const UpdateTasksOrderRequestSchema = z.object({ "order": z.array(z.string().min(1)).min(1) });
export type UpdateTasksOrderRequest = z.infer<typeof UpdateTasksOrderRequestSchema>;

export const DeleteTaskRequestSchema = z.object({ "task": z.string().min(1) });
export type DeleteTaskRequest = z.infer<typeof DeleteTaskRequestSchema>;

export const EditTaskRequestSchema = z.object({ "old_task": z.string().min(1), "new_task": z.string().min(1), "prompt_template": z.union([z.string(), z.null()]).default(null), "response_rules": z.union([z.string(), z.null()]).default(null), "output_skeleton": z.union([z.string(), z.null()]).default(null), "input_examples": z.union([z.string(), z.null()]).default(null), "output_examples": z.union([z.string(), z.null()]).default(null) });
export type EditTaskRequest = z.infer<typeof EditTaskRequestSchema>;

export const AddTaskRequestSchema = z.object({ "title": z.string().min(1), "prompt_content": z.string().min(1), "response_rules": z.string().default(""), "output_skeleton": z.string().default(""), "input_examples": z.string().default(""), "output_examples": z.string().default("") });
export type AddTaskRequest = z.infer<typeof AddTaskRequestSchema>;

export const PromptAssistRequestSchema = z.object({ "target": z.enum(["task_modal","shared_prompt_modal"]), "action": z.enum(["generate_draft","improve","shorten","expand","generate_examples"]), "fields": z.object({ "title": z.string().max(256).default(""), "content": z.string().max(4000).default(""), "prompt_content": z.string().max(4000).default(""), "category": z.string().max(256).default(""), "author": z.string().max(256).default(""), "prompt_type": z.string().default("text"), "input_examples": z.string().max(4000).default(""), "output_examples": z.string().max(4000).default(""), "ai_model": z.string().max(256).default("") }).optional() });
export type PromptAssistRequest = z.infer<typeof PromptAssistRequestSchema>;

export const SharedPromptCreateRequestSchema = z.object({ "title": z.string().min(1), "category": z.string().min(1), "content": z.string().min(1), "author": z.string().min(1), "prompt_type": z.enum(["text","image"]).default("text"), "input_examples": z.string().default(""), "output_examples": z.string().default(""), "ai_model": z.string().default("") });
export type SharedPromptCreateRequest = z.infer<typeof SharedPromptCreateRequestSchema>;

export const BookmarkCreateRequestSchema = z.object({ "title": z.string().min(1), "content": z.string().min(1), "input_examples": z.string().default(""), "output_examples": z.string().default("") });
export type BookmarkCreateRequest = z.infer<typeof BookmarkCreateRequestSchema>;

export const BookmarkDeleteRequestSchema = z.object({ "title": z.string().min(1) });
export type BookmarkDeleteRequest = z.infer<typeof BookmarkDeleteRequestSchema>;

export const PromptListEntryCreateRequestSchema = z.object({ "prompt_id": z.number().int() });
export type PromptListEntryCreateRequest = z.infer<typeof PromptListEntryCreateRequestSchema>;

export const PromptUpdateRequestSchema = z.object({ "title": z.string().min(1), "category": z.string().min(1), "content": z.string().min(1), "input_examples": z.string().default(""), "output_examples": z.string().default("") });
export type PromptUpdateRequest = z.infer<typeof PromptUpdateRequestSchema>;

export const MemoCreateRequestSchema = z.object({ "input_content": z.string().default(""), "ai_response": z.string().min(1), "title": z.string().default(""), "tags": z.string().default("") });
export type MemoCreateRequest = z.infer<typeof MemoCreateRequestSchema>;

export const ShareMemoRequestSchema = z.object({ "memo_id": z.number().int() });
export type ShareMemoRequest = z.infer<typeof ShareMemoRequestSchema>;

export const ApiErrorPayloadSchema = z.object({ "error": z.union([z.string(), z.null()]).default(null), "message": z.union([z.string(), z.null()]).default(null), "detail": z.union([z.string(), z.array(z.union([z.string(), z.object({ "msg": z.union([z.string(), z.null()]).default(null) }).catchall(z.any())])), z.null()]).default(null) }).catchall(z.any());
export type ApiErrorPayload = z.infer<typeof ApiErrorPayloadSchema>;

export const ApiDetailObjectSchema = z.object({ "msg": z.union([z.string(), z.null()]).default(null) }).catchall(z.any());
export type ApiDetailObject = z.infer<typeof ApiDetailObjectSchema>;

export const ChatJsonResponseSchema = z.object({ "error": z.union([z.string(), z.null()]).default(null), "message": z.union([z.string(), z.null()]).default(null), "detail": z.union([z.string(), z.array(z.union([z.string(), z.object({ "msg": z.union([z.string(), z.null()]).default(null) }).catchall(z.any())])), z.null()]).default(null), "response": z.union([z.string(), z.null()]).default(null) }).catchall(z.any());
export type ChatJsonResponse = z.infer<typeof ChatJsonResponseSchema>;

export const ChatGenerationStatusResponseSchema = z.object({ "error": z.union([z.string(), z.null()]).default(null), "message": z.union([z.string(), z.null()]).default(null), "detail": z.union([z.string(), z.array(z.union([z.string(), z.object({ "msg": z.union([z.string(), z.null()]).default(null) }).catchall(z.any())])), z.null()]).default(null), "is_generating": z.union([z.boolean(), z.null()]).default(null), "has_replayable_job": z.union([z.boolean(), z.null()]).default(null) }).catchall(z.any());
export type ChatGenerationStatusResponse = z.infer<typeof ChatGenerationStatusResponseSchema>;

export const ChatHistoryMessageSchema = z.object({ "id": z.union([z.number().int(), z.null()]).default(null), "message": z.union([z.string(), z.null()]).default(null), "sender": z.union([z.string(), z.null()]).default(null), "timestamp": z.union([z.string(), z.null()]).default(null) }).catchall(z.any());
export type ChatHistoryMessage = z.infer<typeof ChatHistoryMessageSchema>;

export const ChatHistoryPaginationSchema = z.object({ "has_more": z.union([z.boolean(), z.null()]).default(null), "next_before_id": z.union([z.number().int(), z.null()]).default(null), "limit": z.union([z.number().int(), z.null()]).default(null) }).catchall(z.any());
export type ChatHistoryPagination = z.infer<typeof ChatHistoryPaginationSchema>;

export const ChatHistoryResponseSchema = z.object({ "error": z.union([z.string(), z.null()]).default(null), "message": z.union([z.string(), z.null()]).default(null), "detail": z.union([z.string(), z.array(z.union([z.string(), z.object({ "msg": z.union([z.string(), z.null()]).default(null) }).catchall(z.any())])), z.null()]).default(null), "messages": z.union([z.array(z.object({ "id": z.union([z.number().int(), z.null()]).default(null), "message": z.union([z.string(), z.null()]).default(null), "sender": z.union([z.string(), z.null()]).default(null), "timestamp": z.union([z.string(), z.null()]).default(null) }).catchall(z.any())), z.null()]).default(null), "pagination": z.union([z.object({ "has_more": z.union([z.boolean(), z.null()]).default(null), "next_before_id": z.union([z.number().int(), z.null()]).default(null), "limit": z.union([z.number().int(), z.null()]).default(null) }).catchall(z.any()), z.null()]).default(null) }).catchall(z.any());
export type ChatHistoryResponse = z.infer<typeof ChatHistoryResponseSchema>;

export const ShareChatRoomResponseSchema = z.object({ "error": z.union([z.string(), z.null()]).default(null), "message": z.union([z.string(), z.null()]).default(null), "detail": z.union([z.string(), z.array(z.union([z.string(), z.object({ "msg": z.union([z.string(), z.null()]).default(null) }).catchall(z.any())])), z.null()]).default(null), "share_token": z.union([z.string(), z.null()]).default(null), "share_url": z.union([z.string(), z.null()]).default(null) }).catchall(z.any());
export type ShareChatRoomResponse = z.infer<typeof ShareChatRoomResponseSchema>;

export const StoredChatHistoryEntrySchema = z.object({ "text": z.union([z.string(), z.null()]).default(null), "sender": z.union([z.string(), z.null()]).default(null) }).catchall(z.any());
export type StoredChatHistoryEntry = z.infer<typeof StoredChatHistoryEntrySchema>;

export const PromptRecordApiSchema = z.object({ "id": z.union([z.number().int(), z.string(), z.null()]).default(null), "title": z.string(), "content": z.string(), "category": z.union([z.string(), z.null()]).default(""), "input_examples": z.union([z.string(), z.null()]).default(""), "output_examples": z.union([z.string(), z.null()]).default(""), "created_at": z.union([z.string(), z.null()]).default(null) }).catchall(z.any());
export type PromptRecordApi = z.infer<typeof PromptRecordApiSchema>;

export const PromptListEntryApiSchema = z.object({ "id": z.union([z.number().int(), z.string(), z.null()]).default(null), "prompt_id": z.union([z.number().int(), z.string(), z.null()]).default(null), "created_at": z.union([z.string(), z.null()]).default(null), "prompt": z.object({ "id": z.union([z.number().int(), z.string(), z.null()]).default(null), "title": z.string(), "content": z.string(), "category": z.union([z.string(), z.null()]).default(""), "input_examples": z.union([z.string(), z.null()]).default(""), "output_examples": z.union([z.string(), z.null()]).default(""), "created_at": z.union([z.string(), z.null()]).default(null) }).catchall(z.any()) }).catchall(z.any());
export type PromptListEntryApi = z.infer<typeof PromptListEntryApiSchema>;

export const PromptListEntryLegacyApiSchema = z.object({ "id": z.union([z.number().int(), z.string(), z.null()]).default(null), "title": z.string(), "content": z.string(), "category": z.union([z.string(), z.null()]).default(""), "input_examples": z.union([z.string(), z.null()]).default(""), "output_examples": z.union([z.string(), z.null()]).default(""), "created_at": z.union([z.string(), z.null()]).default(null), "prompt_id": z.union([z.number().int(), z.string(), z.null()]).default(null) }).catchall(z.any());
export type PromptListEntryLegacyApi = z.infer<typeof PromptListEntryLegacyApiSchema>;

export const MyPromptsApiResponseSchema = z.object({ "prompts": z.array(z.object({ "id": z.union([z.number().int(), z.string(), z.null()]).default(null), "title": z.string(), "content": z.string(), "category": z.union([z.string(), z.null()]).default(""), "input_examples": z.union([z.string(), z.null()]).default(""), "output_examples": z.union([z.string(), z.null()]).default(""), "created_at": z.union([z.string(), z.null()]).default(null) }).catchall(z.any())).optional() }).catchall(z.any());
export type MyPromptsApiResponse = z.infer<typeof MyPromptsApiResponseSchema>;

export const PromptListApiResponseSchema = z.object({ "prompts": z.array(z.union([z.object({ "id": z.union([z.number().int(), z.string(), z.null()]).default(null), "prompt_id": z.union([z.number().int(), z.string(), z.null()]).default(null), "created_at": z.union([z.string(), z.null()]).default(null), "prompt": z.object({ "id": z.union([z.number().int(), z.string(), z.null()]).default(null), "title": z.string(), "content": z.string(), "category": z.union([z.string(), z.null()]).default(""), "input_examples": z.union([z.string(), z.null()]).default(""), "output_examples": z.union([z.string(), z.null()]).default(""), "created_at": z.union([z.string(), z.null()]).default(null) }).catchall(z.any()) }).catchall(z.any()), z.object({ "id": z.union([z.number().int(), z.string(), z.null()]).default(null), "title": z.string(), "content": z.string(), "category": z.union([z.string(), z.null()]).default(""), "input_examples": z.union([z.string(), z.null()]).default(""), "output_examples": z.union([z.string(), z.null()]).default(""), "created_at": z.union([z.string(), z.null()]).default(null), "prompt_id": z.union([z.number().int(), z.string(), z.null()]).default(null) }).catchall(z.any())])).optional() }).catchall(z.any());
export type PromptListApiResponse = z.infer<typeof PromptListApiResponseSchema>;

export const PromptManageMutationApiResponseSchema = z.object({ "message": z.union([z.string(), z.null()]).default(null) }).catchall(z.any());
export type PromptManageMutationApiResponse = z.infer<typeof PromptManageMutationApiResponseSchema>;

export const MemoSaveResponseSchema = z.object({ "status": z.union([z.string(), z.null()]).default(null) }).catchall(z.any());
export type MemoSaveResponse = z.infer<typeof MemoSaveResponseSchema>;
