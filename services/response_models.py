from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ResponsePayloadModel(BaseModel):
    # 応答ペイロードは将来の拡張キーを受け入れる。
    # Allow forward-compatible response payload keys.
    model_config = ConfigDict(extra="allow")


class ApiDetailObject(ResponsePayloadModel):
    msg: str | None = None


class ApiErrorPayload(ResponsePayloadModel):
    error: str | None = None
    message: str | None = None
    detail: str | list[str | ApiDetailObject] | None = None


class ChatJsonResponse(ApiErrorPayload):
    response: str | None = None


class ChatGenerationStatusResponse(ApiErrorPayload):
    is_generating: bool | None = None
    has_replayable_job: bool | None = None


class ChatHistoryMessage(ResponsePayloadModel):
    id: int | None = None
    message: str | None = None
    sender: str | None = None
    timestamp: str | None = None


class ChatHistoryPagination(ResponsePayloadModel):
    has_more: bool | None = None
    next_before_id: int | None = None
    limit: int | None = None


class ChatHistoryResponse(ApiErrorPayload):
    messages: list[ChatHistoryMessage] | None = None
    pagination: ChatHistoryPagination | None = None


class ShareChatRoomResponse(ApiErrorPayload):
    share_token: str | None = None
    share_url: str | None = None


class StoredChatHistoryEntry(ResponsePayloadModel):
    text: str | None = None
    sender: str | None = None


class PromptRecordApi(ResponsePayloadModel):
    id: int | str | None = None
    title: str
    content: str
    category: str | None = ""
    input_examples: str | None = ""
    output_examples: str | None = ""
    created_at: str | None = None


class PromptListEntryApi(ResponsePayloadModel):
    id: int | str | None = None
    prompt_id: int | str | None = None
    created_at: str | None = None
    prompt: PromptRecordApi


class PromptListEntryLegacyApi(PromptRecordApi):
    id: int | str | None = None
    prompt_id: int | str | None = None
    created_at: str | None = None


class MyPromptsApiResponse(ResponsePayloadModel):
    prompts: list[PromptRecordApi] = Field(default_factory=list)


class PromptListApiResponse(ResponsePayloadModel):
    prompts: list[PromptListEntryApi | PromptListEntryLegacyApi] = Field(default_factory=list)


class PromptManageMutationApiResponse(ResponsePayloadModel):
    message: str | None = None


class MemoSaveResponse(ResponsePayloadModel):
    status: str | None = None
