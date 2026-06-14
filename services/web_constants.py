from __future__ import annotations

import os

# フロントエンドのベースURL。環境変数から取得し、未設定の場合はローカルホストをデフォルトとする
# The base URL of the frontend. Loaded from environment variables, defaulting to localhost if unset.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# プロジェクトのベースディレクトリへの絶対パス
# The absolute path to the project's base directory.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# サーバー内部エラー発生時にユーザーへ提示するデフォルトのメッセージ
# The default message shown to the user when an internal server error occurs.
DEFAULT_INTERNAL_ERROR_MESSAGE = "内部エラーが発生しました。"

