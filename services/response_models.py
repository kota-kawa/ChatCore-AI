from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# 日本語: ResponsePayloadModel に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ResponsePayloadModel.
class ResponsePayloadModel(BaseModel):
    # 応答ペイロードは将来の拡張キーを受け入れる。
    # Allow forward-compatible response payload keys.
    model_config = ConfigDict(extra="allow")


# 日本語: ApiDetailObject に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ApiDetailObject.
class ApiDetailObject(ResponsePayloadModel):
    msg: str | None = None


# 日本語: ApiErrorPayload に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ApiErrorPayload.
class ApiErrorPayload(ResponsePayloadModel):
    error: str | None = None
    message: str | None = None
    detail: str | list[str | ApiDetailObject] | None = None


# 日本語: ChatJsonResponse に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatJsonResponse.
class ChatJsonResponse(ApiErrorPayload):
    response: str | None = None


# 日本語: ChatGenerationStatusResponse に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatGenerationStatusResponse.
class ChatGenerationStatusResponse(ApiErrorPayload):
    is_generating: bool | None = None
    has_replayable_job: bool | None = None


# 日本語: ChatHistoryMessage に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatHistoryMessage.
class ChatHistoryMessage(ResponsePayloadModel):
    id: int | None = None
    message: str | None = None
    sender: str | None = None
    timestamp: str | None = None


# 日本語: ChatHistoryPagination に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatHistoryPagination.
class ChatHistoryPagination(ResponsePayloadModel):
    has_more: bool | None = None
    next_before_id: int | None = None
    limit: int | None = None


# 日本語: ChatHistoryResponse に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatHistoryResponse.
class ChatHistoryResponse(ApiErrorPayload):
    messages: list[ChatHistoryMessage] | None = None
    pagination: ChatHistoryPagination | None = None


# 日本語: ShareChatRoomResponse に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ShareChatRoomResponse.
class ShareChatRoomResponse(ApiErrorPayload):
    share_token: str | None = None
    share_url: str | None = None


# 日本語: StoredChatHistoryEntry に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to StoredChatHistoryEntry.
class StoredChatHistoryEntry(ResponsePayloadModel):
    text: str | None = None
    sender: str | None = None


# 日本語: PromptRecordApi に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptRecordApi.
class PromptRecordApi(ResponsePayloadModel):
    id: int | str | None = None
    title: str
    content: str
    category: str | None = ""
    input_examples: str | None = ""
    output_examples: str | None = ""
    created_at: str | None = None


# 日本語: PromptListEntryApi に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptListEntryApi.
class PromptListEntryApi(ResponsePayloadModel):
    id: int | str | None = None
    prompt_id: int | str | None = None
    created_at: str | None = None
    prompt: PromptRecordApi


# 日本語: PromptListEntryLegacyApi に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptListEntryLegacyApi.
class PromptListEntryLegacyApi(PromptRecordApi):
    id: int | str | None = None
    prompt_id: int | str | None = None
    created_at: str | None = None


# 日本語: MyPromptsApiResponse に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MyPromptsApiResponse.
class MyPromptsApiResponse(ResponsePayloadModel):
    prompts: list[PromptRecordApi] = Field(default_factory=list)


# 日本語: PromptListApiResponse に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptListApiResponse.
class PromptListApiResponse(ResponsePayloadModel):
    prompts: list[PromptListEntryApi | PromptListEntryLegacyApi] = Field(default_factory=list)


# 日本語: PromptManageMutationApiResponse に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptManageMutationApiResponse.
class PromptManageMutationApiResponse(ResponsePayloadModel):
    message: str | None = None


# 日本語: MemoSaveResponse に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MemoSaveResponse.
class MemoSaveResponse(ResponsePayloadModel):
    status: str | None = None
