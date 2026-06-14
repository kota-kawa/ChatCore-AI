from __future__ import annotations

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


# 日本語: プロンプトリストの要素レコードを表すモデル（ネストされたプロンプトオブジェクト形式）。
# English: Model representing a list entry record with a nested prompt object.
class PromptListEntryApi(ResponsePayloadModel):
    id: int | str | None = None
    prompt_id: int | str | None = None
    created_at: str | None = None
    prompt: PromptRecordApi


# 日本語: フラットな構造で表された互換用（レガシー）のプロンプトリスト要素モデル。
# English: Legacy list entry model representation with a flat structure.
class PromptListEntryLegacyApi(PromptRecordApi):
    id: int | str | None = None
    prompt_id: int | str | None = None
    created_at: str | None = None


# 日本語: ユーザーが作成したプロンプトリストを返す応答モデル。
# English: Response model returning the user's created prompts list.
class MyPromptsApiResponse(ResponsePayloadModel):
    prompts: list[PromptRecordApi] = Field(default_factory=list)


# 日本語: プロンプト（およびSKILL）の一覧データを返す応答モデル。
# English: Response model returning a list of prompts/SKILLs.
class PromptListApiResponse(ResponsePayloadModel):
    prompts: list[PromptListEntryApi | PromptListEntryLegacyApi] = Field(default_factory=list)


# 日本語: プロンプトの追加・変更・削除結果の成否メッセージを返す応答モデル。
# English: Response model returning the status message of prompt mutations.
class PromptManageMutationApiResponse(ResponsePayloadModel):
    message: str | None = None


# 日本語: メモ保存結果のステータスを返す応答モデル。
# English: Response model returning status after saving a memo.
class MemoSaveResponse(ResponsePayloadModel):
    status: str | None = None
