"""フロントエンドの URL、プロジェクトのベースディレクトリなど、Web 層の共通定数。

Shared web-layer constants such as the frontend URL and the project base directory.
"""

from __future__ import annotations

import os

# 環境変数が未設定のときに使うフロントエンドのベースURL
# The frontend base URL used when the environment variable is unset.
DEFAULT_FRONTEND_URL = "http://localhost:3000"

# フロントエンドのベースURL。環境変数から取得し、未設定の場合はローカルホストをデフォルトとする
# The base URL of the frontend. Loaded from environment variables, defaulting to localhost if unset.
FRONTEND_URL = os.getenv("FRONTEND_URL", DEFAULT_FRONTEND_URL)

# プロジェクトのベースディレクトリへの絶対パス
# The absolute path to the project's base directory.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
