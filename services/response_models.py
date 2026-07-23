from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# 日本語: すべてのAPIレスポンスペイロードの共通基底モデル。将来の拡張キーを許容します。
# English: Common base model for all response payloads. Allows forward-compatible extra keys.
class ResponsePayloadModel(BaseModel):
    # 応答ペイロードは将来の拡張キーを受け入れる。
    # Allow forward-compatible response payload keys.
    model_config = ConfigDict(extra="allow")


# 日本語: エラーの追加詳細メッセージを格納するデータ構造。
# English: Data structure holding supplementary error details.
class ApiDetailObject(ResponsePayloadModel):
    msg: str | None = None


# 日本語: 標準的なエラー応答のペイロードスキーマ。
# English: Standard error response payload schema.
class ApiErrorPayload(ResponsePayloadModel):
    error: str | None = None
    message: str | None = None
    detail: str | list[str | ApiDetailObject] | None = None


# 日本語: チャットボットの応答テキストを含むJSONレスポンスモデル。
# English: JSON response model containing the chatbot's text response.
class ChatJsonResponse(ApiErrorPayload):
    response: str | None = None


# 日本語: チャットの生成状況（応答生成中か、再実行可能なジョブがあるか）を表すモデル。
# English: Model representing chat generation status (generating state, replayable jobs).
class ChatGenerationStatusResponse(ApiErrorPayload):
    is_generating: bool | None = None
    has_replayable_job: bool | None = None


# 日本語: チャット履歴における個々のメッセージデータを表現するモデル。
# English: Model representing an individual message in chat history.
class ChatHistoryMessage(ResponsePayloadModel):
    id: int | None = None
    message: str | None = None
    sender: str | None = None
    timestamp: str | None = None


# 日本語: チャット履歴のページネーション情報を保持するメタデータモデル。
# English: Metadata model holding pagination details for chat history.
class ChatHistoryPagination(ResponsePayloadModel):
    has_more: bool | None = None
    next_before_id: int | None = None
    limit: int | None = None


# 日本語: チャット履歴リストとページネーション情報を含む応答モデル。
# English: Response model containing list of messages and pagination metadata.
class ChatHistoryResponse(ApiErrorPayload):
    messages: list[ChatHistoryMessage] | None = None
    pagination: ChatHistoryPagination | None = None


# 日本語: チャットルームの共有リンク生成結果を返す応答モデル。
# English: Response model returning shared link generation results.
class ShareChatRoomResponse(ApiErrorPayload):
    share_token: str | None = None
    share_url: str | None = None


# 日本語: データベースなどに永続化されているシンプルなチャット発言レコードのモデル。
# English: Simple chat history record model persisted in database storage.
class StoredChatHistoryEntry(ResponsePayloadModel):
    text: str | None = None
    sender: str | None = None


# 日本語: 登録済みのプロンプト単体レコードの詳細情報を表すモデル。
# English: Model representing detail fields of a single prompt record.
class PromptRecordApi(ResponsePayloadModel):
    id: int | str | None = None
    title: str
    content: str
    category: str | None = ""
    input_examples: str | None = ""
    output_examples: str | None = ""
    created_at: str | None = None


# 日本語: いいねしたプロンプト要素レコードを表すモデル。
# English: Model representing a liked prompt list entry.
class LikedPromptApi(PromptRecordApi):
    id: int | str | None = None
    like_id: int | str | None = None
    prompt_id: int | str | None = None
    author: str | None = None
    # 2軸モデルの正準フィールド。
    # Canonical two-axis fields.
    content_format: str | None = "prompt"
    media_type: str | None = "text"
    attributes: dict[str, str] = Field(default_factory=dict)
    attachments: list[dict[str, str]] = Field(default_factory=list)
    # 旧フィールドは後方互換のための派生値 (保存はしない)。
    # Legacy fields kept as derived values for backward compatibility (not persisted).
    prompt_type: str | None = "text"
    reference_image_url: str | None = None
    skill_markdown: str | None = ""
    skill_python_script: str | None = ""
    prompt_created_at: str | None = None
    liked_at: str | None = None
    liked: bool = True


# 日本語: ユーザーが作成したプロンプトリストを返す応答モデル。
# English: Response model returning the user's created prompts list.
class MyPromptsApiResponse(ResponsePayloadModel):
    prompts: list[PromptRecordApi] = Field(default_factory=list)


# 日本語: いいねしたプロンプト一覧データを返す応答モデル。
# English: Response model returning a list of liked prompts.
class LikedPromptsApiResponse(ResponsePayloadModel):
    prompts: list[LikedPromptApi] = Field(default_factory=list)


# 日本語: プロンプトの追加・変更・削除結果の成否メッセージを返す応答モデル。
# English: Response model returning the status message of prompt mutations.
class PromptManageMutationApiResponse(ResponsePayloadModel):
    message: str | None = None


# 日本語: メモ保存結果のステータスを返す応答モデル。
# English: Response model returning status after saving a memo.
class MemoSaveResponse(ResponsePayloadModel):
    status: str | None = None


# 日本語: パーソナル・コンテキスト金庫の1件の事実を表す応答モデル。
# English: Response model representing a single personal context vault fact.
class ContextFactResponse(ResponsePayloadModel):
    id: int
    fact_type: Literal["preference", "profile", "project", "decision", "reference"]
    title: str
    content: str
    status: Literal["active", "deprecated"]
    revision: int
    source_kind: Literal["manual", "chat", "mcp", "import"] = "manual"
    importance: int = Field(default=50, ge=0, le=100)
    created_at: str | None = None
    updated_at: str | None = None


# 日本語: コンテキスト事実の一覧と keyset ページングカーソルを返す応答モデル。
# English: Response model returning a list of context facts with a keyset cursor.
class ContextFactListResponse(ResponsePayloadModel):
    facts: list[ContextFactResponse] = Field(default_factory=list)
    total_active: int = 0
    next_cursor: str | None = None


# 日本語: ユーザー確認待ちの自動抽出候補。内部fingerprint等は公開しない。
# English: Allowlisted extracted candidate awaiting user review.
class ContextFactCandidateResponse(ResponsePayloadModel):
    id: int
    fact_type: Literal["preference", "profile", "project", "decision", "reference"]
    title: str
    content: str
    source_kind: Literal["manual", "chat", "mcp", "import"] = "chat"
    source_ref: str | None = None
    importance: int = Field(default=50, ge=0, le=100)
    confidence: float = Field(default=0, ge=0, le=1)
    status: Literal["pending", "approved", "rejected"]
    revision: int = Field(ge=1)
    created_at: str | None = None
    updated_at: str | None = None


class ContextFactCandidateListResponse(ResponsePayloadModel):
    candidates: list[ContextFactCandidateResponse] = Field(default_factory=list)
    next_cursor: str | None = None
    total_pending: int = 0


class ContextFactCandidateApprovalResponse(ResponsePayloadModel):
    candidate: ContextFactCandidateResponse
    fact: ContextFactResponse


class ContextExtractionSettingsResponse(ResponsePayloadModel):
    enabled: bool = False


# 日本語: fact_type ごとにまとめた active な事実のグループ。
# English: Group of active facts collected under one fact_type.
class ContextDigestGroup(ResponsePayloadModel):
    fact_type: str
    facts: list[ContextFactResponse] = Field(default_factory=list)


# 日本語: get_personal_context が返す軽量ダイジェスト応答モデル。
# English: Compact digest response returned by get_personal_context.
class ContextDigestResponse(ResponsePayloadModel):
    facts_total: int = 0
    total_active: int = 0
    returned_count: int = 0
    omitted_count: int = 0
    truncated: bool = False
    groups: list[ContextDigestGroup] = Field(default_factory=list)
