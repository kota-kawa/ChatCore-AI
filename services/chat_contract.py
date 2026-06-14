from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

_DEFAULT_CHAT_HISTORY_PAGE_SIZE = 50
_DEFAULT_CHAT_HISTORY_PAGE_SIZE_MAX = 100
_DEFAULT_API_REQUEST_CASE = "snake_case"
_DEFAULT_API_RESPONSE_CASE = "snake_case"
_DEFAULT_FRONTEND_INTERNAL_CASE = "camelCase"
_DEFAULT_DATETIME_SERIALIZATION = "iso-8601"


# 日本語: to positive int に関する処理の入口です。
# English: Entry point for logic related to to positive int.
def _to_positive_int(value: Any, fallback: int) -> int:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if isinstance(value, bool):
        return fallback
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


# 日本語: load chat contract の読み込み処理を担当します。
# English: Handle loading for load chat contract.
def _load_chat_contract() -> dict[str, Any]:
    contract_path = (
        Path(__file__).resolve().parent.parent
        / "frontend"
        / "data"
        / "chat_contract.json"
    )
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        raw = contract_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Chat contract file not found: %s", contract_path)
        return {}
    except OSError:
        logger.exception("Failed to read chat contract file: %s", contract_path)
        return {}

    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.exception("Failed to parse chat contract JSON: %s", contract_path)
        return {}

    if not isinstance(parsed, dict):
        logger.warning("Chat contract root must be an object: %s", contract_path)
        return {}
    return parsed


_CHAT_CONTRACT = _load_chat_contract()
_CHAT_HISTORY = _CHAT_CONTRACT.get("chat_history")
if not isinstance(_CHAT_HISTORY, dict):
    _CHAT_HISTORY = {}

_API = _CHAT_CONTRACT.get("api")
if not isinstance(_API, dict):
    _API = {}

CHAT_HISTORY_PAGE_SIZE_DEFAULT: Final[int] = _to_positive_int(
    _CHAT_HISTORY.get("page_size_default"),
    _DEFAULT_CHAT_HISTORY_PAGE_SIZE,
)
CHAT_HISTORY_PAGE_SIZE_MAX: Final[int] = max(
    CHAT_HISTORY_PAGE_SIZE_DEFAULT,
    _to_positive_int(
        _CHAT_HISTORY.get("page_size_max"),
        _DEFAULT_CHAT_HISTORY_PAGE_SIZE_MAX,
    ),
)

API_REQUEST_CASE: Final[str] = str(_API.get("request_case") or _DEFAULT_API_REQUEST_CASE)
API_RESPONSE_CASE: Final[str] = str(_API.get("response_case") or _DEFAULT_API_RESPONSE_CASE)
API_FRONTEND_INTERNAL_CASE: Final[str] = str(
    _API.get("frontend_internal_case") or _DEFAULT_FRONTEND_INTERNAL_CASE
)
API_DATETIME_SERIALIZATION: Final[str] = str(
    _API.get("datetime_serialization") or _DEFAULT_DATETIME_SERIALIZATION
)
