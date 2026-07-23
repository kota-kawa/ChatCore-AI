from __future__ import annotations

# APIエラーメッセージの共通定義ファイルです。各サービスやルートで再利用可能なテキストを一元管理します。
# Centralized API error message definitions to allow reuse across services and routes.

# 認証関連のエラーメッセージ定義です。
# Error message definitions related to authentication.
ERROR_LOGIN_REQUIRED = "ログインが必要です"
ERROR_INVALID_JSON = "JSON形式が不正です。"
ERROR_TOKEN_REQUIRED = "token is required"

# チャットや共有機能関連のエラーメッセージ定義です。
# Error message definitions related to chat and sharing functionality.
ERROR_CHAT_ROOM_NOT_FOUND = "該当ルームが見つかりません"
ERROR_SHARED_LINK_NOT_FOUND = "共有リンクが見つかりません"
ERROR_MEMO_NOT_FOUND_FOR_SHARE = "共有対象のメモが見つかりません。"
ERROR_INVALID_PROMPT_FEED_CURSOR = "プロンプト一覧のカーソルが不正です。"
ERROR_INVALID_PROMPT_FEED_FILTER = "プロンプト一覧の絞り込み条件が不正です。"
ERROR_CONTEXT_FACT_IDEMPOTENCY_CONFLICT = (
    "同じ冪等キーが別のコンテキスト保存に使用されています。"
)
ERROR_CONTEXT_FACT_NOT_FOUND = "該当するコンテキストが見つかりません。"
ERROR_CONTEXT_FACT_REVISION_CONFLICT = (
    "他の場所で先に更新されました。最新の内容を読み込み直してからやり直してください。"
)
ERROR_CONTEXT_FACT_LIMIT_REACHED = (
    "保存できる有効なコンテキストは200件までです。"
    "不要な項目を無効化してから追加してください。"
)
ERROR_CONTEXT_FACT_CANDIDATE_NOT_FOUND = (
    "該当するコンテキスト候補が見つかりません。"
)
ERROR_CONTEXT_FACT_CANDIDATE_REVISION_CONFLICT = (
    "候補は他の場所で先に更新されました。最新の一覧を読み込み直してください。"
)
ERROR_CONTEXT_FACT_CANDIDATE_CURSOR_INVALID = (
    "候補一覧のページングカーソルが不正です。"
)
ERROR_CONTEXT_FACT_CANDIDATE_STATUS_INVALID = "候補状態の指定が不正です。"
ERROR_CONTEXT_FACT_CANDIDATE_APPROVE_PAYLOAD_INVALID = (
    "revisionと有効な候補内容を指定してください。"
)
ERROR_CONTEXT_FACT_CANDIDATE_REJECT_PAYLOAD_INVALID = "revisionを指定してください。"
ERROR_CONTEXT_EXTRACTION_SETTINGS_NOT_FOUND = "抽出設定の対象ユーザーが見つかりません。"
ERROR_CONTEXT_EXTRACTION_SETTINGS_PAYLOAD_INVALID = (
    "enabledにはtrueまたはfalseを指定してください。"
)
