from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.attached_files import (
    MAX_ATTACHED_FILE_BASE64_LENGTH,
    MAX_ATTACHED_FILE_CONTENT_LENGTH,
    MAX_ATTACHED_FILES,
)
from services.prompt_types import (
    DEFAULT_CONTENT_FORMAT,
    DEFAULT_MEDIA_TYPE,
    normalize_content_format,
    normalize_media_type,
    requires_content,
    sanitize_attributes,
    validate_attributes,
)

NonEmptyStr = Annotated[str, Field(min_length=1)]

# RFC 5321 caps the full address at 254 chars. The pattern is a deliberately
# strict subset — it rejects CR/LF (mail-header injection) and any non-printable
# whitespace, which is the whole point of pre-validating before the address is
# used as an SMTP envelope or written into a `To:` header.
EMAIL_ADDRESS_MAX_LENGTH = 254
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


# 日本語: メールアドレスの文字列長、改行コードなどの無効文字、正規表現パターンを検証し、小文字化して返します。
# English: Validate email address length, invalid characters (e.g. CR/LF), regex pattern, and return it lowercased.
def _validate_email_address(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError("メールアドレスが指定されていません")
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


# 日本語: すべてのAPIリクエストペイロードモデルの共通基底クラス。余分なフィールドを無視し、文字列の空白をトリムします。
# English: Common base class for all request payload models. Ignores extra fields and strips whitespaces.
class RequestPayloadModel(BaseModel):
    # 余分なキーを無視しつつ文字列の前後空白を自動で除去する共通ベース
    # Common base model that strips string whitespace and ignores extra fields.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# 日本語: メールアドレス登録またはログイン用のリクエストペイロード。
# English: Request payload for email address registration or login.
class EmailRequest(RequestPayloadModel):
    # メールアドレス入力用ペイロード
    # Payload for email address input.
    email: NonEmptyStr

    @model_validator(mode="after")
    def _normalize_email(self) -> "EmailRequest":
        self.email = _validate_email_address(self.email)
        return self


# 日本語: 新しいメールアドレスへの変更を要求するリクエストペイロード。
# English: Request payload to change to a new email address.
class EmailChangeRequest(RequestPayloadModel):
    # メールアドレス変更APIの入力（新しいメールアドレス）
    # Payload for the email-change request endpoint.
    new_email: NonEmptyStr

    @model_validator(mode="after")
    def _normalize_new_email(self) -> "EmailChangeRequest":
        self.new_email = _validate_email_address(self.new_email)
        return self


# 日本語: メールアドレス変更の確認用コードを含むリクエストペイロード。
# English: Request payload confirming email change with a verification code.
class EmailChangeConfirmRequest(RequestPayloadModel):
    # メールアドレス変更確認APIの入力（受信した6桁コード）
    # Payload to confirm an email change with the verification code.
    auth_code: NonEmptyStr


# 日本語: ログイン認証コード入力用リクエストペイロード。
# English: Request payload containing the authentication code for verification.
class AuthCodeRequest(RequestPayloadModel):
    # 認証コード送信用ペイロード
    # Payload for verification/login code input.
    authCode: str | None = None


# 日本語: 新しいチャットルームを作成する際のリクエストペイロード。
# English: Request payload for creating a new chat room.
class NewChatRoomRequest(RequestPayloadModel):
    # チャットルーム新規作成APIの入力
    # Input payload for chat room creation.
    id: str
    title: str = "新規チャット"
    mode: Literal["normal", "temporary"] = "normal"
    # 所属させるプロジェクトID（任意）。指定時は作成後にルームを紐づける。
    # Optional project to assign the new room to (linked after creation).
    project_id: int | None = None


# 日本語: 特定のチャットルームIDを対象とする操作のリクエストペイロード。
# English: Request payload targetting a single chat room ID.
class ChatRoomIdRequest(RequestPayloadModel):
    room_id: ChatRoomIdStr


# 日本語: 複数のチャットルームIDを一括操作する際のリクエストペイロード。
# English: Request payload containing a list of chat room IDs for bulk actions.
class ChatRoomIdsRequest(RequestPayloadModel):
    room_ids: list[ChatRoomIdStr] = Field(min_length=1, max_length=100)


# 日本語: チャットルームのタイトルを変更する際のリクエストペイロード。
# English: Request payload for renaming a chat room.
class RenameChatRoomRequest(RequestPayloadModel):
    room_id: ChatRoomIdStr
    new_title: NonEmptyStr


# 日本語: チャットルームの共有リンクを生成する際のリクエストペイロード。
# English: Request payload for sharing a chat room.
class ShareChatRoomRequest(RequestPayloadModel):
    room_id: ChatRoomIdStr


# 日本語: チャットに添付された個々のファイルを表現するデータモデル。
# English: Data model representing an individual file attached to a chat.
class AttachedFileItem(RequestPayloadModel):
    name: str = Field(min_length=1, max_length=256)
    content: str = Field(default="", max_length=MAX_ATTACHED_FILE_CONTENT_LENGTH)
    media_type: str = Field(default="", max_length=128)
    data_base64: str = Field(default="", max_length=MAX_ATTACHED_FILE_BASE64_LENGTH)


# 日本語: プロジェクト（ワークスペース）作成のリクエストペイロード。
# English: Request payload for creating a project (workspace).
class ProjectCreateRequest(RequestPayloadModel):
    name: str = Field(default="新規プロジェクト", max_length=255)
    instructions: str = Field(default="", max_length=20000)


# 日本語: プロジェクトの名前・指示を更新するリクエストペイロード。
# English: Request payload for updating a project's name/instructions.
class ProjectUpdateRequest(RequestPayloadModel):
    project_id: int
    name: str | None = Field(default=None, max_length=255)
    instructions: str | None = Field(default=None, max_length=20000)


# 日本語: プロジェクトIDを対象とする操作のリクエストペイロード。
# English: Request payload targetting a single project ID.
class ProjectIdRequest(RequestPayloadModel):
    project_id: int


# 日本語: チャットルームをプロジェクトへ所属/解除するリクエストペイロード。
# English: Request payload for assigning/unassigning a room to a project.
class AssignRoomProjectRequest(RequestPayloadModel):
    room_id: ChatRoomIdStr
    project_id: int | None = None


# 日本語: 新しいチャットメッセージと添付ファイルを含むリクエストペイロード。
# English: Request payload for sending a chat message with optional attachments.
class ChatMessageRequest(RequestPayloadModel):
    message: ChatMessageStr
    chat_room_id: ChatRoomIdStr = "default"
    model: ModelNameStr | None = None
    attached_files: list[AttachedFileItem] = Field(default_factory=list, max_length=MAX_ATTACHED_FILES)


# 日本語: 定型タスクの並び順（IDリスト）を更新するリクエストペイロード。
# English: Request payload to update the ordering of preset tasks.
class UpdateTasksOrderRequest(RequestPayloadModel):
    order: list[NonEmptyStr] = Field(min_length=1)


# 日本語: 特定のタスクを削除する際のリクエストペイロード。
# English: Request payload for deleting a specific task.
class DeleteTaskRequest(RequestPayloadModel):
    task: NonEmptyStr


# 日本語: 既存のタスク定義を編集する際のリクエストペイロード。
# English: Request payload for editing an existing task definition.
class EditTaskRequest(RequestPayloadModel):
    old_task: NonEmptyStr
    new_task: NonEmptyStr
    prompt_template: str | None = None
    response_rules: str | None = None
    output_skeleton: str | None = None
    input_examples: str | None = None
    output_examples: str | None = None


# 日本語: 新しいカスタムタスクを追加する際のリクエストペイロード。
# English: Request payload for adding a new custom task.
class AddTaskRequest(RequestPayloadModel):
    title: NonEmptyStr
    prompt_content: NonEmptyStr
    response_rules: str = ""
    output_skeleton: str = ""
    input_examples: str = ""
    output_examples: str = ""


# 日本語: プロンプトAIアシストに入力される、各フォームフィールドの値を表すモデル。
# English: Model representing values of input fields passed to the prompt AI assist.
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


# 日本語: プロンプトAIアシスト（下書き・改善など）を実行するリクエストペイロード。
# English: Request payload for executing the prompt AI assist actions.
class PromptAssistRequest(RequestPayloadModel):
    target: Literal["task_modal", "shared_prompt_modal"]
    action: Literal["generate_draft", "improve", "shorten", "expand", "generate_examples"]
    instruction: str = Field(default="", max_length=MAX_PROMPT_ASSIST_TEXT_LENGTH)
    fields: PromptAssistFields = Field(default_factory=PromptAssistFields)


# 日本語: AIエージェント（画面操作エージェント）に渡す会話メッセージ履歴のデータモデル。
# English: Data model for chat history messages passed to the UI-operating AI agent.
class AiAgentMessage(RequestPayloadModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


# 日本語: AIエージェントに画面操作などのアクションプランを算出させるリクエストペイロード。
# English: Request payload for prompting the AI agent to plan screen execution actions.
class AiAgentRequest(RequestPayloadModel):
    messages: list[AiAgentMessage] = Field(min_length=1, max_length=20)
    current_page: str | None = Field(default=None, max_length=256)
    current_dom: str | None = Field(default=None, max_length=12000)
    memo_id: int | None = Field(default=None, ge=1)


# 日本語: 共有プロンプト（またはSKILL）を新しく投稿する際のリクエストペイロード。
# English: Request payload for posting a new shared prompt or SKILL.
class SharedPromptCreateRequest(RequestPayloadModel):
    title: NonEmptyStr
    category: str = ""
    content: str = ""
    # 2軸モデル: フォーマット軸 (prompt/skill...) × メディア軸 (text/image...)。
    # Two-axis model: content format axis × media type axis. See services/prompt_types.py.
    content_format: str = DEFAULT_CONTENT_FORMAT
    media_type: str = DEFAULT_MEDIA_TYPE
    input_examples: str = ""
    output_examples: str = ""
    ai_model: str = ""
    # フォーマット固有の構造化フィールド (例: skill_markdown)。許可キーのみ採用。
    # Format-specific structured fields (e.g. skill_markdown); only declared keys are kept.
    attributes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_two_axis(self) -> "SharedPromptCreateRequest":
        # 日本語: 軸の値を正規化し、フォーマットが宣言する属性のみ採用・検証します。
        # English: Normalize the axes and keep/validate only the attributes the format declares.
        self.content_format = normalize_content_format(self.content_format)
        self.media_type = normalize_media_type(self.media_type)
        self.attributes = sanitize_attributes(self.content_format, self.attributes)
        errors = validate_attributes(self.content_format, self.attributes)
        if errors:
            raise ValueError(errors[0])
        if requires_content(self.content_format) and not self.content:
            raise ValueError("通常投稿では content が必須です。")
        return self


# 日本語: 共有プロンプトからマイスペースのタスクとしてコピー登録する際のリクエストペイロード。
# English: Request payload for importing a shared prompt into my space tasks.
class PromptTaskCreateRequest(RequestPayloadModel):
    prompt_id: int


# 日本語: プロンプトに「いいね」を付与・解除する際のリクエストペイロード。
# English: Request payload for toggling/submitting a "like" on a prompt.
class PromptLikeRequest(RequestPayloadModel):
    prompt_id: int


# 日本語: プロンプトに対して新しいコメントを投稿する際のリクエストペイロード。
# English: Request payload for posting a comment on a prompt.
class PromptCommentCreateRequest(RequestPayloadModel):
    content: str = Field(min_length=1, max_length=MAX_PROMPT_COMMENT_LENGTH)


# 日本語: 不適切なコメントを通報する際のリクエストペイロード。
# English: Request payload for reporting an inappropriate comment.
class PromptCommentReportRequest(RequestPayloadModel):
    reason: Literal["spam", "harassment", "abuse", "other"] = "abuse"
    details: str = Field(default="", max_length=MAX_PROMPT_COMMENT_REPORT_DETAILS_LENGTH)


# 日本語: 投稿済みの共有プロンプトの内容を更新する際のリクエストペイロード。
# English: Request payload for updating an already posted shared prompt.
class PromptUpdateRequest(RequestPayloadModel):
    title: NonEmptyStr
    category: NonEmptyStr
    content: NonEmptyStr
    input_examples: str = ""
    output_examples: str = ""


# 日本語: 新しいメモを作成し、指定のコレクションや配色で保存する際のリクエストペイロード。
# English: Request payload for creating a new memo with options like collections and colors.
class MemoCreateRequest(RequestPayloadModel):
    # メモ保存APIの入力
    # Input payload for memo creation API.
    ai_response: str = ""
    title: str = ""
    collection_id: int | None = None
    background_color: str | None = Field(default=None, max_length=20, pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

    @model_validator(mode="after")
    def _require_content(self) -> "MemoCreateRequest":
        # 日本語: 保存する回答内容が空でないことを確認します。
        # English: Ensure that the response text is not empty before saving.
        if not self.ai_response.strip():
            raise ValueError("AIの回答を入力してください。")
        return self


# 日本語: メモの共有トークンを作成する際のリクエストペイロード。
# English: Request payload for initiating a memo share.
class ShareMemoRequest(RequestPayloadModel):
    memo_id: int


# 日本語: メモのタイトル、本文、配色、所属コレクションを更新する際のリクエストペイロード。
# English: Request payload for updating memo title, content, color, or collection.
class MemoUpdateRequest(RequestPayloadModel):
    title: str | None = None
    ai_response: str | None = None
    collection_id: int | None = Field(default=None)
    clear_collection: bool = False
    background_color: str | None = Field(default=None, max_length=20, pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    clear_background_color: bool = False


# 日本語: メモの有効化/無効化（アーカイブ状態等）を切り替える際のリクエストペイロード。
# English: Request payload for toggling the enabled/disabled state of a memo.
class MemoToggleRequest(RequestPayloadModel):
    enabled: bool = True


# 日本語: メモの共有期間や更新フラグを指定して共有リンクを生成する際のリクエストペイロード。
# English: Request payload for generating a shared link with expiration and refresh configurations.
class MemoShareCreateRequest(RequestPayloadModel):
    force_refresh: bool = False
    expires_in_days: int | None = Field(default=30, ge=1, le=3650)


# 日本語: 保存した回答テキストから、AIにタイトルやタグの提案を求める際のリクエストペイロード。
# English: Request payload for asking AI to suggest titles and tags from the response body.
class MemoSuggestRequest(RequestPayloadModel):
    # AI タイトル・タグ提案APIの入力
    # Input payload for AI-powered title/tag suggestion.
    ai_response: NonEmptyStr


# 日本語: 複数のメモを一括して削除、アーカイブ、コレクション設定する際のリクエストペイロード。
# English: Request payload for executing bulk actions (delete, archive, collections) on multiple memos.
class MemoBulkActionRequest(RequestPayloadModel):
    # 一括操作APIの入力
    # Input payload for bulk memo operations.
    action: Literal["delete", "archive", "unarchive", "pin", "unpin", "set_collection", "clear_collection"]
    memo_ids: list[int] = Field(min_length=1, max_length=200)
    collection_id: int | None = None


# 日本語: メモカードのドラッグ＆ドロップによる並べ替え（挿入位置）を指定するリクエストペイロード。
# English: Request payload specifying destination bounds for dragging and dropping a memo card.
class MemoReorderRequest(RequestPayloadModel):
    # メモカードのドラッグ並べ替え入力
    # Input payload for drag-and-drop memo card reordering.
    memo_id: int
    before_id: int | None = None
    after_id: int | None = None


# 日本語: メモ整理用のコレクション（フォルダ）を新規作成する際のリクエストペイロード。
# English: Request payload for creating a new memo collection folder.
class MemoCollectionCreateRequest(RequestPayloadModel):
    # コレクション作成APIの入力
    # Input payload for memo collection creation.
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(default="#6b7280", max_length=20)


# 日本語: メモコレクションの表示名やカラーコードを更新する際のリクエストペイロード。
# English: Request payload for updating the name or color code of a memo collection.
class MemoCollectionUpdateRequest(RequestPayloadModel):
    # コレクション更新APIの入力
    # Input payload for memo collection update.
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, max_length=20)
