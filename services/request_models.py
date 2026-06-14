from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.attached_files import (
    MAX_ATTACHED_FILE_BASE64_LENGTH,
    MAX_ATTACHED_FILE_CONTENT_LENGTH,
    MAX_ATTACHED_FILES,
)

NonEmptyStr = Annotated[str, Field(min_length=1)]

# RFC 5321 caps the full address at 254 chars. The pattern is a deliberately
# strict subset — it rejects CR/LF (mail-header injection) and any non-printable
# whitespace, which is the whole point of pre-validating before the address is
# used as an SMTP envelope or written into a `To:` header.
EMAIL_ADDRESS_MAX_LENGTH = 254
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


# 日本語: validate email address の検証処理を担当します。
# English: Handle validating for validate email address.
def _validate_email_address(value: str) -> str:
    cleaned = (value or "").strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not cleaned:
        raise ValueError("メールアドレスが指定されていません")
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if len(cleaned) > EMAIL_ADDRESS_MAX_LENGTH:
        raise ValueError("メールアドレスが長すぎます")
    if any(ch in cleaned for ch in ("\r", "\n", "\t", "\x00")):
        raise ValueError("メールアドレスに使用できない文字が含まれています")
    if not _EMAIL_RE.match(cleaned):
        raise ValueError("メールアドレスの形式が正しくありません")
    return cleaned.lower()
# Keep backend validation aligned with the frontend chat input limit.
MAX_CHAT_MESSAGE_LENGTH = 30000
MAX_CHAT_ROOM_ID_LENGTH = 128
MAX_MODEL_NAME_LENGTH = 64
MAX_PROMPT_ASSIST_TEXT_LENGTH = 4000
MAX_PROMPT_ASSIST_META_LENGTH = 256
MAX_PROMPT_COMMENT_LENGTH = 1000
MAX_PROMPT_COMMENT_REPORT_DETAILS_LENGTH = 500
MAX_SHARED_PROMPT_SKILL_TEXT_LENGTH = 30000

ChatMessageStr = Annotated[str, Field(min_length=1, max_length=MAX_CHAT_MESSAGE_LENGTH)]
ChatRoomIdStr = Annotated[str, Field(min_length=1, max_length=MAX_CHAT_ROOM_ID_LENGTH)]
ModelNameStr = Annotated[str, Field(min_length=1, max_length=MAX_MODEL_NAME_LENGTH)]


# 日本語: RequestPayloadModel に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to RequestPayloadModel.
class RequestPayloadModel(BaseModel):
    # 余分なキーを無視しつつ文字列の前後空白を自動で除去する共通ベース
    # Common base model that strips string whitespace and ignores extra fields.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# 日本語: EmailRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to EmailRequest.
class EmailRequest(RequestPayloadModel):
    # メールアドレス入力用ペイロード
    # Payload for email address input.
    email: NonEmptyStr

    # 日本語: normalize email の正規化処理を担当します。
    # English: Handle normalizing for normalize email.
    @model_validator(mode="after")
    def _normalize_email(self) -> "EmailRequest":
        self.email = _validate_email_address(self.email)
        return self


# 日本語: EmailChangeRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to EmailChangeRequest.
class EmailChangeRequest(RequestPayloadModel):
    # メールアドレス変更APIの入力（新しいメールアドレス）
    # Payload for the email-change request endpoint.
    new_email: NonEmptyStr

    # 日本語: normalize new email の正規化処理を担当します。
    # English: Handle normalizing for normalize new email.
    @model_validator(mode="after")
    def _normalize_new_email(self) -> "EmailChangeRequest":
        self.new_email = _validate_email_address(self.new_email)
        return self


# 日本語: EmailChangeConfirmRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to EmailChangeConfirmRequest.
class EmailChangeConfirmRequest(RequestPayloadModel):
    # メールアドレス変更確認APIの入力（受信した6桁コード）
    # Payload to confirm an email change with the verification code.
    auth_code: NonEmptyStr


# 日本語: AuthCodeRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to AuthCodeRequest.
class AuthCodeRequest(RequestPayloadModel):
    # 認証コード送信用ペイロード
    # Payload for verification/login code input.
    authCode: str | None = None


# 日本語: NewChatRoomRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to NewChatRoomRequest.
class NewChatRoomRequest(RequestPayloadModel):
    # チャットルーム新規作成APIの入力
    # Input payload for chat room creation.
    id: str
    title: str = "新規チャット"
    mode: Literal["normal", "temporary"] = "normal"


# 日本語: ChatRoomIdRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatRoomIdRequest.
class ChatRoomIdRequest(RequestPayloadModel):
    room_id: ChatRoomIdStr


# 日本語: ChatRoomIdsRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatRoomIdsRequest.
class ChatRoomIdsRequest(RequestPayloadModel):
    room_ids: list[ChatRoomIdStr] = Field(min_length=1, max_length=100)


# 日本語: RenameChatRoomRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to RenameChatRoomRequest.
class RenameChatRoomRequest(RequestPayloadModel):
    room_id: ChatRoomIdStr
    new_title: NonEmptyStr


# 日本語: ShareChatRoomRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ShareChatRoomRequest.
class ShareChatRoomRequest(RequestPayloadModel):
    room_id: ChatRoomIdStr


# 日本語: AttachedFileItem に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to AttachedFileItem.
class AttachedFileItem(RequestPayloadModel):
    name: str = Field(min_length=1, max_length=256)
    content: str = Field(default="", max_length=MAX_ATTACHED_FILE_CONTENT_LENGTH)
    media_type: str = Field(default="", max_length=128)
    data_base64: str = Field(default="", max_length=MAX_ATTACHED_FILE_BASE64_LENGTH)


# 日本語: ChatMessageRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatMessageRequest.
class ChatMessageRequest(RequestPayloadModel):
    message: ChatMessageStr
    chat_room_id: ChatRoomIdStr = "default"
    model: ModelNameStr | None = None
    attached_files: list[AttachedFileItem] = Field(default_factory=list, max_length=MAX_ATTACHED_FILES)


# 日本語: UpdateTasksOrderRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to UpdateTasksOrderRequest.
class UpdateTasksOrderRequest(RequestPayloadModel):
    order: list[NonEmptyStr] = Field(min_length=1)


# 日本語: DeleteTaskRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to DeleteTaskRequest.
class DeleteTaskRequest(RequestPayloadModel):
    task: NonEmptyStr


# 日本語: EditTaskRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to EditTaskRequest.
class EditTaskRequest(RequestPayloadModel):
    old_task: NonEmptyStr
    new_task: NonEmptyStr
    prompt_template: str | None = None
    response_rules: str | None = None
    output_skeleton: str | None = None
    input_examples: str | None = None
    output_examples: str | None = None


# 日本語: AddTaskRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to AddTaskRequest.
class AddTaskRequest(RequestPayloadModel):
    title: NonEmptyStr
    prompt_content: NonEmptyStr
    response_rules: str = ""
    output_skeleton: str = ""
    input_examples: str = ""
    output_examples: str = ""


# 日本語: PromptAssistFields に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptAssistFields.
class PromptAssistFields(RequestPayloadModel):
    title: str = Field(default="", max_length=MAX_PROMPT_ASSIST_META_LENGTH)
    content: str = Field(default="", max_length=MAX_PROMPT_ASSIST_TEXT_LENGTH)
    prompt_content: str = Field(default="", max_length=MAX_PROMPT_ASSIST_TEXT_LENGTH)
    skill_markdown: str = Field(default="", max_length=MAX_SHARED_PROMPT_SKILL_TEXT_LENGTH)
    skill_python_script: str = Field(default="", max_length=MAX_SHARED_PROMPT_SKILL_TEXT_LENGTH)
    category: str = Field(default="", max_length=MAX_PROMPT_ASSIST_META_LENGTH)
    author: str = Field(default="", max_length=MAX_PROMPT_ASSIST_META_LENGTH)
    prompt_type: str = "text"
    input_examples: str = Field(default="", max_length=MAX_PROMPT_ASSIST_TEXT_LENGTH)
    output_examples: str = Field(default="", max_length=MAX_PROMPT_ASSIST_TEXT_LENGTH)
    ai_model: str = Field(default="", max_length=MAX_PROMPT_ASSIST_META_LENGTH)


# 日本語: PromptAssistRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptAssistRequest.
class PromptAssistRequest(RequestPayloadModel):
    target: Literal["task_modal", "shared_prompt_modal"]
    action: Literal["generate_draft", "improve", "shorten", "expand", "generate_examples"]
    instruction: str = Field(default="", max_length=MAX_PROMPT_ASSIST_TEXT_LENGTH)
    fields: PromptAssistFields = Field(default_factory=PromptAssistFields)


# 日本語: AiAgentMessage に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to AiAgentMessage.
class AiAgentMessage(RequestPayloadModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


# 日本語: AiAgentRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to AiAgentRequest.
class AiAgentRequest(RequestPayloadModel):
    messages: list[AiAgentMessage] = Field(min_length=1, max_length=20)
    current_page: str | None = Field(default=None, max_length=256)
    current_dom: str | None = Field(default=None, max_length=12000)
    memo_id: int | None = Field(default=None, ge=1)


# 日本語: SharedPromptCreateRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to SharedPromptCreateRequest.
class SharedPromptCreateRequest(RequestPayloadModel):
    title: NonEmptyStr
    category: str = ""
    content: str = ""
    prompt_type: Literal["text", "image", "skill"] = "text"
    input_examples: str = ""
    output_examples: str = ""
    ai_model: str = ""
    skill_markdown: str = Field(default="", max_length=MAX_SHARED_PROMPT_SKILL_TEXT_LENGTH)
    skill_python_script: str = Field(default="", max_length=MAX_SHARED_PROMPT_SKILL_TEXT_LENGTH)

    # 日本語: validate skill fields の検証処理を担当します。
    # English: Handle validating for validate skill fields.
    @model_validator(mode="after")
    def validate_skill_fields(self) -> "SharedPromptCreateRequest":
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self.prompt_type == "skill":
            if not self.skill_markdown:
                raise ValueError("SKILL投稿では skill_markdown が必須です。")
            return self
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not self.content:
            raise ValueError("通常投稿では content が必須です。")
        return self


# 日本語: BookmarkCreateRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to BookmarkCreateRequest.
class BookmarkCreateRequest(RequestPayloadModel):
    prompt_id: int


# 日本語: BookmarkDeleteRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to BookmarkDeleteRequest.
class BookmarkDeleteRequest(RequestPayloadModel):
    prompt_id: int


# 日本語: PromptTaskCreateRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptTaskCreateRequest.
class PromptTaskCreateRequest(RequestPayloadModel):
    prompt_id: int


# 日本語: PromptListEntryCreateRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptListEntryCreateRequest.
class PromptListEntryCreateRequest(RequestPayloadModel):
    prompt_id: int


# 日本語: PromptLikeRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptLikeRequest.
class PromptLikeRequest(RequestPayloadModel):
    prompt_id: int


# 日本語: PromptCommentCreateRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptCommentCreateRequest.
class PromptCommentCreateRequest(RequestPayloadModel):
    content: str = Field(min_length=1, max_length=MAX_PROMPT_COMMENT_LENGTH)


# 日本語: PromptCommentReportRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptCommentReportRequest.
class PromptCommentReportRequest(RequestPayloadModel):
    reason: Literal["spam", "harassment", "abuse", "other"] = "abuse"
    details: str = Field(default="", max_length=MAX_PROMPT_COMMENT_REPORT_DETAILS_LENGTH)


# 日本語: PromptUpdateRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptUpdateRequest.
class PromptUpdateRequest(RequestPayloadModel):
    title: NonEmptyStr
    category: NonEmptyStr
    content: NonEmptyStr
    input_examples: str = ""
    output_examples: str = ""


# 日本語: MemoCreateRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MemoCreateRequest.
class MemoCreateRequest(RequestPayloadModel):
    # メモ保存APIの入力
    # Input payload for memo creation API.
    ai_response: str = ""
    title: str = ""
    collection_id: int | None = None
    background_color: str | None = Field(default=None, max_length=20, pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

    # 日本語: require content に関する処理の入口です。
    # English: Entry point for logic related to require content.
    @model_validator(mode="after")
    def _require_content(self) -> "MemoCreateRequest":
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not self.ai_response.strip():
            raise ValueError("AIの回答を入力してください。")
        return self


# 日本語: ShareMemoRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ShareMemoRequest.
class ShareMemoRequest(RequestPayloadModel):
    memo_id: int


# 日本語: MemoUpdateRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MemoUpdateRequest.
class MemoUpdateRequest(RequestPayloadModel):
    title: str | None = None
    ai_response: str | None = None
    collection_id: int | None = Field(default=None)
    clear_collection: bool = False
    background_color: str | None = Field(default=None, max_length=20, pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    clear_background_color: bool = False


# 日本語: MemoToggleRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MemoToggleRequest.
class MemoToggleRequest(RequestPayloadModel):
    enabled: bool = True


# 日本語: MemoShareCreateRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MemoShareCreateRequest.
class MemoShareCreateRequest(RequestPayloadModel):
    force_refresh: bool = False
    expires_in_days: int | None = Field(default=30, ge=1, le=3650)


# 日本語: MemoSuggestRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MemoSuggestRequest.
class MemoSuggestRequest(RequestPayloadModel):
    # AI タイトル・タグ提案APIの入力
    # Input payload for AI-powered title/tag suggestion.
    ai_response: NonEmptyStr


# 日本語: MemoBulkActionRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MemoBulkActionRequest.
class MemoBulkActionRequest(RequestPayloadModel):
    # 一括操作APIの入力
    # Input payload for bulk memo operations.
    action: Literal["delete", "archive", "unarchive", "pin", "unpin", "set_collection", "clear_collection"]
    memo_ids: list[int] = Field(min_length=1, max_length=200)
    collection_id: int | None = None


# 日本語: MemoReorderRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MemoReorderRequest.
class MemoReorderRequest(RequestPayloadModel):
    # メモカードのドラッグ並べ替え入力
    # Input payload for drag-and-drop memo card reordering.
    memo_id: int
    before_id: int | None = None
    after_id: int | None = None


# 日本語: MemoCollectionCreateRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MemoCollectionCreateRequest.
class MemoCollectionCreateRequest(RequestPayloadModel):
    # コレクション作成APIの入力
    # Input payload for memo collection creation.
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(default="#6b7280", max_length=20)


# 日本語: MemoCollectionUpdateRequest に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MemoCollectionUpdateRequest.
class MemoCollectionUpdateRequest(RequestPayloadModel):
    # コレクション更新APIの入力
    # Input payload for memo collection update.
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, max_length=20)
