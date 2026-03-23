from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

NonEmptyStr = Annotated[str, Field(min_length=1)]
MAX_CHAT_MESSAGE_LENGTH = 8000
MAX_CHAT_ROOM_ID_LENGTH = 128
MAX_MODEL_NAME_LENGTH = 64
MAX_PROMPT_ASSIST_TEXT_LENGTH = 4000
MAX_PROMPT_ASSIST_META_LENGTH = 256

ChatMessageStr = Annotated[str, Field(min_length=1, max_length=MAX_CHAT_MESSAGE_LENGTH)]
ChatRoomIdStr = Annotated[str, Field(min_length=1, max_length=MAX_CHAT_ROOM_ID_LENGTH)]
ModelNameStr = Annotated[str, Field(min_length=1, max_length=MAX_MODEL_NAME_LENGTH)]


class RequestPayloadModel(BaseModel):
    # 余分なキーを無視しつつ文字列の前後空白を自動で除去する共通ベース
    # Common base model that strips string whitespace and ignores extra fields.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class EmailRequest(RequestPayloadModel):
    # メールアドレス入力用ペイロード
    # Payload for email address input.
    email: NonEmptyStr


class AuthCodeRequest(RequestPayloadModel):
    # 認証コード送信用ペイロード
    # Payload for verification/login code input.
    authCode: str | None = None


class NewChatRoomRequest(RequestPayloadModel):
    # チャットルーム新規作成APIの入力
    # Input payload for chat room creation.
    id: str
    title: str = "新規チャット"


class ChatRoomIdRequest(RequestPayloadModel):
    room_id: ChatRoomIdStr


class RenameChatRoomRequest(RequestPayloadModel):
    room_id: ChatRoomIdStr
    new_title: NonEmptyStr


class ShareChatRoomRequest(RequestPayloadModel):
    room_id: ChatRoomIdStr


class ChatMessageRequest(RequestPayloadModel):
    message: ChatMessageStr
    chat_room_id: ChatRoomIdStr = "default"
    model: ModelNameStr | None = None


class UpdateTasksOrderRequest(RequestPayloadModel):
    order: list[NonEmptyStr] = Field(min_length=1)


class DeleteTaskRequest(RequestPayloadModel):
    task: NonEmptyStr


class EditTaskRequest(RequestPayloadModel):
    old_task: NonEmptyStr
    new_task: NonEmptyStr
    prompt_template: str | None = None
    response_rules: str | None = None
    output_skeleton: str | None = None
    input_examples: str | None = None
    output_examples: str | None = None


class AddTaskRequest(RequestPayloadModel):
    title: NonEmptyStr
    prompt_content: NonEmptyStr
    response_rules: str = ""
    output_skeleton: str = ""
    input_examples: str = ""
    output_examples: str = ""


class PromptAssistFields(RequestPayloadModel):
    title: str = Field(default="", max_length=MAX_PROMPT_ASSIST_META_LENGTH)
    content: str = Field(default="", max_length=MAX_PROMPT_ASSIST_TEXT_LENGTH)
    prompt_content: str = Field(default="", max_length=MAX_PROMPT_ASSIST_TEXT_LENGTH)
    category: str = Field(default="", max_length=MAX_PROMPT_ASSIST_META_LENGTH)
    author: str = Field(default="", max_length=MAX_PROMPT_ASSIST_META_LENGTH)
    prompt_type: str = "text"
    input_examples: str = Field(default="", max_length=MAX_PROMPT_ASSIST_TEXT_LENGTH)
    output_examples: str = Field(default="", max_length=MAX_PROMPT_ASSIST_TEXT_LENGTH)
    ai_model: str = Field(default="", max_length=MAX_PROMPT_ASSIST_META_LENGTH)


class PromptAssistRequest(RequestPayloadModel):
    target: Literal["task_modal", "shared_prompt_modal"]
    action: Literal["generate_draft", "improve", "shorten", "expand", "generate_examples"]
    fields: PromptAssistFields = Field(default_factory=PromptAssistFields)


class SharedPromptCreateRequest(RequestPayloadModel):
    title: NonEmptyStr
    category: NonEmptyStr
    content: NonEmptyStr
    author: NonEmptyStr
    prompt_type: Literal["text", "image"] = "text"
    input_examples: str = ""
    output_examples: str = ""
    ai_model: str = ""


class BookmarkCreateRequest(RequestPayloadModel):
    title: NonEmptyStr
    content: NonEmptyStr
    input_examples: str = ""
    output_examples: str = ""


class BookmarkDeleteRequest(RequestPayloadModel):
    title: NonEmptyStr


class PromptListEntryCreateRequest(RequestPayloadModel):
    prompt_id: int


class PromptUpdateRequest(RequestPayloadModel):
    title: NonEmptyStr
    category: NonEmptyStr
    content: NonEmptyStr
    input_examples: str = ""
    output_examples: str = ""


class MemoCreateRequest(RequestPayloadModel):
    # メモ保存APIの入力
    # Input payload for memo creation API.
    input_content: str = ""
    ai_response: NonEmptyStr
    title: str = ""
    tags: str = ""


class ShareMemoRequest(RequestPayloadModel):
    memo_id: int
