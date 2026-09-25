from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    code: str | None = None
    params: dict[str, Any] | None = None


# 日本語: 解決済み、または保存済みの表示言語を返す設定APIレスポンス。
# English: Preferences API response carrying the resolved or persisted display language.
class LocalePreferenceResponse(ResponsePayloadModel):
    locale: Literal["ja", "en"]


# 日本語: 利用上限の1つの期間。金額は返さず、上限に対する割合とリセット時刻だけを持つ。
# English: One usage-limit window: the share of the limit used and when it resets, never amounts.
class UsageLimitWindowResponse(ResponsePayloadModel):
    used_ratio: float = Field(ge=0, le=1)
    resets_at: str


# 日本語: 設定画面に表示する利用状況。上限が無効な期間は null。
# English: Usage shown on the settings page; a window is null when its limit is disabled.
class UsageLimitsResponse(ResponsePayloadModel):
    daily: UsageLimitWindowResponse | None
    weekly: UsageLimitWindowResponse | None
    monthly_budget_exhausted: bool
    monthly_resets_at: str


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


# 日本語: デフォルトSkillと個人Skillの一覧・更新結果を表すAPIモデル。
# English: API models for default and personal Skill records and mutation results.
class UserSkillApi(ResponsePayloadModel):
    id: int
    system_skill_key: str | None = None
    name: str
    instructions: str
    is_enabled: bool = True
    is_default: bool = False
    can_edit: bool = True
    can_delete: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class UserSkillsApiResponse(ResponsePayloadModel):
    skills: list[UserSkillApi] = Field(default_factory=list)


class UserSkillMutationApiResponse(ResponsePayloadModel):
    skill: UserSkillApi | None = None
    message: str | None = None


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
    description: str | None = ""
    category: str | None = ""
    input_examples: str | None = ""
    output_examples: str | None = ""
    created_at: str | None = None
    # SKILL 投稿では本文を attributes.skill_markdown に保持するため、
    # 設定画面の一覧・閲覧モーダルでもこの派生フィールドを明示的に返す。
    # Skill posts store their body in attributes.skill_markdown, so expose this
    # derived field explicitly for the settings list and preview modal.
    content_format: str | None = "prompt"
    media_type: str | None = "text"
    attributes: dict[str, str] = Field(default_factory=dict)
    # 設定画面でも投稿時の作例画像を表示できるよう、正準の添付情報と
    # 後方互換URLを通常のプロンプトレコードにも含める。
    # Include canonical attachments and the compatibility URL on regular prompt
    # records so settings views can render the published example image.
    attachments: list[dict[str, str]] = Field(default_factory=list)
    reference_image_url: str | None = None
    skill_markdown: str | None = ""


# 日本語: SKILL投稿に同梱された1件のテキストリソース。
# English: One text resource bundled with a SKILL post.
class PromptResourceApi(ResponsePayloadModel):
    id: int | None = None
    path: str
    role: Literal["script", "reference", "config", "other"] = "other"
    language: str = "text"
    media_type: str = "text/plain"
    content: str = ""
    size_bytes: int = 0
    sha256: str = ""
    sort_order: int = 0
    created_at: str | None = None
    updated_at: str | None = None


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
    resources: list[PromptResourceApi] = Field(default_factory=list)
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


# 日本語: export/importで公開してよい、DB内部値を含まない可搬な事実。
# English: Portable fact safe for export/import, excluding all database-internal fields.
class ContextVaultPortableFact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    fact_type: Literal["preference", "profile", "project", "decision", "reference"]
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2000)
    status: Literal["active", "deprecated"]
    importance: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _require_non_blank_text(self) -> ContextVaultPortableFact:
        if not self.title.strip() or not self.content.strip():
            raise ValueError("Portable context title and content must not be blank.")
        if "\x00" in self.title or "\x00" in self.content:
            raise ValueError("Portable context text must not contain NUL characters.")
        try:
            self.title.encode("utf-8")
            self.content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("Portable context text must be valid UTF-8.") from exc
        return self


# 日本語: Chat-Coreパーソナル・コンテキスト金庫のversion付きJSON形式。
# English: Versioned JSON document for Chat-Core personal context portability.
class ContextVaultExportDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    format: Literal["chat-core-personal-context"]
    version: Literal[1]
    exported_at: str
    facts: list[ContextVaultPortableFact]


class ContextVaultImportPreviewResponse(ResponsePayloadModel):
    preview_token: str
    total_count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    deprecated_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    importable_count: int = Field(ge=0)
    can_import: bool
    sample_facts: list[ContextVaultPortableFact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    expires_at: str


class ContextVaultImportResponse(ResponsePayloadModel):
    status: Literal["success"] = "success"
    imported_count: int = Field(ge=0)
    skipped_duplicate_count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    deprecated_count: int = Field(ge=0)


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


# 日本語: チャットの承認カードで使う値の集合。DB の CHECK 制約・パーツ検証・フロントの型（生成 Zod）がここを正本にする。
#         ツールとプレビューの種類は PR ごとに増やす。
# English: Value sets used by chat approval cards. DB CHECK constraints, part validation and the frontend
#          types (generated Zod) all take them from here. Tools and preview kinds grow PR by PR.
ToolApprovalToolName = Literal["memo_create", "memo_append", "memo_edit"]
ToolApprovalFamily = Literal["memo"]
ToolApprovalStatus = Literal["pending", "succeeded", "failed", "denied", "expired", "superseded", "cancelled"]
ToolApprovalDecision = Literal["once", "always", "auto", "deny"]
ToolApprovalWarning = Literal["shared_memo", "untrusted_input_in_turn"]


# 日本語: 承認カードの部品の基底。メッセージに保存したパーツの検証にも使うため、未知のキーは通さず落とす。
#         本文の空白は差分の一部なので除去しない。
# English: Base of approval-card pieces. They also validate parts stored on messages, so unknown keys are
#          dropped rather than passed through, and whitespace is kept because it is part of the diff.
class ToolApprovalModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


# 日本語: 新しいメモの作成案。
# English: Proposal to create a new memo.
class MemoCreatePreviewApi(ToolApprovalModel):
    kind: Literal["memo_create"]
    title: str = ""
    content: str


# 日本語: 既存メモへの追記案。
# English: Proposal to append text to an existing memo.
class MemoAppendPreviewApi(ToolApprovalModel):
    kind: Literal["memo_append"]
    memo_id: int = Field(ge=1)
    memo_title: str = ""
    text: str
    separator: str = ""


# 日本語: メモの部分置換の1か所（変更前と変更後）。
# English: One replacement in a partial memo edit (before and after).
class MemoEditChangeApi(ToolApprovalModel):
    before: str
    after: str


# 日本語: 既存メモの書き換え案。mode が edits なら部分置換、content なら全文置換。
#         base_revision は提案時の版で、承認時に版が変わっていれば実行しない。
# English: Proposal to rewrite an existing memo: partial replacements for mode "edits", the whole body for
#          mode "content". base_revision is the revision the proposal was made against; approval does not
#          run when the memo has moved on.
class MemoEditPreviewApi(ToolApprovalModel):
    kind: Literal["memo_edit"]
    memo_id: int = Field(ge=1)
    memo_title: str = ""
    new_title: str | None = None
    mode: Literal["edits", "content"]
    edits: list[MemoEditChangeApi] = Field(default_factory=list)
    content: str | None = None
    base_revision: int = Field(ge=1)

    # 日本語: mode と中身が食い違う案はカードに出せないので受け付けない。
    # English: A proposal whose mode disagrees with its payload cannot be shown on a card, so reject it.
    @model_validator(mode="after")
    def _require_payload_for_mode(self) -> MemoEditPreviewApi:
        if self.mode == "edits" and not self.edits:
            raise ValueError("memo_edit preview in edits mode needs at least one edit")
        if self.mode == "content" and self.content is None:
            raise ValueError("memo_edit preview in content mode needs content")
        return self


# 日本語: 実行結果。成功なら対象、失敗なら理由のコード（表示文言はフロントの i18n が持つ）。
# English: Outcome of running the tool: the target on success, a reason code on failure
#          (display text lives in the frontend i18n).
class ToolApprovalResultApi(ToolApprovalModel):
    target_id: int | None = None
    target_title: str | None = None
    error_code: str | None = None


# 日本語: 承認カード1枚。メッセージの tool_approval パーツの approval と承認 API の応答が同じ形を使う。
#         共有表示では readonly にし、preview・result・warnings を持たない。
# English: One approval card. The approval of a message's tool_approval part and the approval API response
#          share this shape. Shared views mark it readonly and carry no preview, result or warnings.
class ToolApprovalApi(ToolApprovalModel):
    id: str = Field(min_length=1)
    tool: ToolApprovalToolName
    family: ToolApprovalFamily
    status: ToolApprovalStatus
    decision: ToolApprovalDecision | None = None
    always_allowed: bool = False
    preview: MemoCreatePreviewApi | MemoAppendPreviewApi | MemoEditPreviewApi | None = None
    warnings: list[ToolApprovalWarning] = Field(default_factory=list)
    expires_at: str | None = None
    result: ToolApprovalResultApi | None = None
    readonly: bool = False

    # 日本語: 操作できるカードは何を実行するかを示せなければならない。プレビューの種類はツールと一致させる。
    # English: An actionable card must show what it will run, and its preview kind must match the tool.
    @model_validator(mode="after")
    def _require_matching_preview(self) -> ToolApprovalApi:
        if self.preview is None:
            if not self.readonly:
                raise ValueError("tool approval needs a preview unless it is readonly")
            return self
        if self.preview.kind != self.tool:
            raise ValueError("tool approval preview kind must match its tool")
        return self


# 日本語: 承認・拒否の結果として更新後のカードを返す応答。
# English: Response carrying the updated card after an approve or deny decision.
class ToolApprovalDecisionResponse(ResponsePayloadModel):
    approval: ToolApprovalApi


# 日本語: 「常に承認」を付与済みのツール1件。
# English: One tool the user has granted "always approve" to.
class ToolAutoApprovalApi(ResponsePayloadModel):
    tool_name: ToolApprovalToolName
    family: ToolApprovalFamily
    created_at: str


class ToolAutoApprovalsResponse(ResponsePayloadModel):
    grants: list[ToolAutoApprovalApi] = Field(default_factory=list)


# 日本語: 取り消し結果。付与が無かった場合も成功とし revoked を false にする（冪等）。
# English: Revocation result. A missing grant still succeeds with revoked false (idempotent).
class ToolAutoApprovalRevokeResponse(ResponsePayloadModel):
    revoked: bool
