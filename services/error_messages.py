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
ERROR_CHAT_EMPTY_RESPONSE = "AIからの回答が空でした。もう一度お試しください。"
ERROR_SHARED_LINK_NOT_FOUND = "共有リンクが見つかりません"
ERROR_TASK_NOT_FOUND = "対象のタスクが見つかりません。"
ERROR_TASK_NAME_CONFLICT = "同じ名前のタスクがすでに存在します。"
ERROR_TASK_ORDER_INVALID = "タスクの並び順が最新の一覧と一致しません。再読み込みしてからやり直してください。"
ERROR_SKILL_NOT_FOUND = "対象のSkillが見つかりません。"
ERROR_SKILL_NAME_CONFLICT = "同じ名前のSkillがすでに存在します。"
ERROR_SKILL_LIMIT_REACHED = "追加できるSkillは20件までです。"
ERROR_DEFAULT_SKILL_IMMUTABLE = "デフォルトSkillは削除・編集できません。"
ERROR_SHARED_SKILL_NOT_FOUND = "対象の公開Skillが見つかりませんでした。"
ERROR_SHARED_SKILL_INVALID_TYPE = "指定された投稿はSkillではありません。"
ERROR_SHARED_SKILL_CONTENT_MISSING = "追加できるSkill本文がありません。"
MESSAGE_SHARED_SKILL_ADDED = "Skillに追加しました。"
MESSAGE_SHARED_SKILL_ALREADY_ADDED = "すでにSkillに追加済みです。"
ERROR_MEMO_NOT_FOUND_FOR_SHARE = "共有対象のメモが見つかりません。"
ERROR_INVALID_PROMPT_FEED_CURSOR = "プロンプト一覧のカーソルが不正です。"
ERROR_INVALID_PROMPT_FEED_FILTER = "プロンプト一覧の絞り込み条件が不正です。"
ERROR_PROMPT_NOT_FOUND = "プロンプトが見つかりません"
ERROR_PROMPT_ATTACHMENT_EMPTY = "空の添付ファイルはアップロードできません。"
ERROR_PROMPT_ATTACHMENT_FORMAT_MISMATCH = "ファイル拡張子と画像形式が一致しません。"
ERROR_PROMPT_ATTACHMENT_MEDIA_UNSUPPORTED = "このメディアタイプはファイル添付に対応していません。"
ERROR_PROMPT_ATTACHMENT_FILENAME_INVALID = "添付ファイル名が不正です。"
ERROR_PROMPT_ATTACHMENT_MIME_UNSUPPORTED = "許可されていない形式の添付ファイルです。"
ERROR_PROMPT_ATTACHMENT_NOT_FOUND = "添付画像が見つかりません。"
ERROR_MCP_PROMPT_IMAGE_BASE64_INVALID = "画像のBase64データを読み取れませんでした。"
ERROR_MCP_PROMPT_IMAGE_DATA_URL_INVALID = "画像データURLはBase64形式で指定してください。"
ERROR_MCP_PROMPT_IMAGE_MIME_UNSUPPORTED = "対応していない画像のMIMEタイプです。"
ERROR_MCP_PROMPT_IMAGE_TOO_LARGE = "画像データが大きすぎます。5MB以下の画像を指定してください。"
ERROR_MCP_PROMPT_IMAGE_FORMAT_UNKNOWN = (
    "画像形式を判別できませんでした。PNG、JPEG、WebP、GIFを指定してください。"
)
ERROR_MCP_PROMPT_IMAGE_METADATA_MISMATCH = "画像データURLとimage_mime_typeの指定が一致しません。"
ERROR_MCP_PROMPT_IMAGE_METADATA_WITHOUT_DATA = (
    "image_base64を指定せずに画像のファイル名やMIMEタイプは指定できません。"
)
ERROR_MCP_PROMPT_IMAGE_SOURCE_CONFLICT = (
    "image_fileとimage_base64は同時に指定できません。どちらか一方を指定してください。"
)
ERROR_MCP_PROMPT_IMAGE_REQUIRED = "image_fileまたはimage_base64で画像を指定してください。"
ERROR_MCP_PROMPT_IMAGE_DOWNLOAD_URL_INVALID = (
    "画像ファイルのダウンロードURLが許可されていません。元画像のバイトを取得できる場合は、"
    "チャンク式アップロードで再試行してください。"
)
ERROR_MCP_PROMPT_IMAGE_DOWNLOAD_FAILED = (
    "画像ファイルを取得できませんでした。元画像のバイトを取得できる場合は、"
    "チャンク式アップロードで再試行してください。"
)
ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED = (
    "画像の一時アップロードが見つからないか、有効期限が切れています。最初から再試行してください。"
)
ERROR_MCP_PROMPT_IMAGE_UPLOAD_CHUNK_INVALID = "画像のBase64チャンクが不正です。"
ERROR_MCP_PROMPT_IMAGE_UPLOAD_CHUNK_ORDER = (
    "画像チャンクの順序が不正です。返されたnext_chunk_indexから再開してください。"
)
ERROR_MCP_PROMPT_IMAGE_UPLOAD_INCOMPLETE = (
    "画像の一時アップロードが未完了です。残りのチャンクを送信してから再試行してください。"
)
ERROR_MCP_PROMPT_IMAGE_UPLOAD_LIMIT = (
    "同時に保持できる画像の一時アップロード数を超えています。不要なアップロードをキャンセルしてから再試行してください。"
)
ERROR_GUEST_PROMPT_TEXT_ONLY = (
    "ゲスト投稿ではテキストプロンプトのみ投稿できます。"
)
ERROR_GUEST_PROMPT_URL_FORBIDDEN = "ゲスト投稿ではURLを含めることはできません。"
ERROR_GUEST_PROMPT_LIMIT_REACHED = "ゲスト投稿は24時間に1件までです。"
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
ERROR_CONTEXT_VAULT_IMPORT_TOO_LARGE = "インポートファイルは10MiB以下にしてください。"
ERROR_CONTEXT_VAULT_IMPORT_REQUEST_TOO_LARGE = (
    "インポートリクエストのサイズが上限を超えています。"
)
ERROR_CONTEXT_VAULT_IMPORT_TOO_MANY = (
    "一度にインポートできるコンテキストは1000件までです。"
)
ERROR_CONTEXT_VAULT_IMPORT_EMPTY = "インポート対象のコンテキストがありません。"
ERROR_CONTEXT_VAULT_IMPORT_JSON_INVALID = "JSONインポート形式が不正です。"
ERROR_CONTEXT_VAULT_IMPORT_MARKDOWN_VERSION_INVALID = (
    "Markdownインポートの形式またはバージョンが不正です。"
)
ERROR_CONTEXT_VAULT_IMPORT_MARKDOWN_BLOCK_INVALID = (
    "Markdown内のcontext-factブロックが不正です。"
)
ERROR_CONTEXT_VAULT_IMPORT_MARKDOWN_FACT_INVALID = (
    "Markdown内のコンテキスト形式が不正です。"
)
ERROR_CONTEXT_VAULT_IMPORT_FORMAT_INVALID = "インポート形式が不正です。"
ERROR_CONTEXT_VAULT_IMPORT_PAYLOAD_INVALID = (
    "format、content、preview_tokenの指定を確認してください。"
)
ERROR_CONTEXT_VAULT_IMPORT_PREVIEW_UNAVAILABLE = (
    "インポートの確認情報を作成できません。"
)
ERROR_CONTEXT_VAULT_IMPORT_PREVIEW_EXPIRED = (
    "インポートの確認期限が切れました。もう一度プレビューしてください。"
)
ERROR_CONTEXT_VAULT_IMPORT_PREVIEW_INVALID = "インポートの確認情報が不正です。"
ERROR_CONTEXT_VAULT_IMPORT_PREVIEW_MISMATCH = (
    "プレビューした内容とインポート内容が一致しません。"
)
ERROR_CONTEXT_VAULT_EXPORT_TOO_MANY = (
    "コンテキストが1000件を超えるため、一括エクスポートできません。"
)
ERROR_CONTEXT_VAULT_EXPORT_TOO_LARGE = (
    "エクスポートデータが10MiBを超えるため、一括ダウンロードできません。"
)
ERROR_CONTEXT_VAULT_EXPORT_FORMAT_INVALID = "エクスポート形式が不正です。"
ERROR_CONTEXT_VAULT_PORTABILITY_FAILED = (
    "コンテキストのエクスポートまたはインポートを完了できませんでした。"
)
WARNING_CONTEXT_VAULT_IMPORT_ACTIVE_LIMIT = (
    "有効なコンテキストが200件を超えるため、この内容はインポートできません。"
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
