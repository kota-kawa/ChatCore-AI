from __future__ import annotations

import os

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_INTERNAL_ERROR_MESSAGE = "内部エラーが発生しました。"
