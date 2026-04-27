from __future__ import annotations

import json
import logging
import re
from typing import Literal

from services.llm import GPT_OSS_20B_LEGACY_MODEL, get_llm_response

logger = logging.getLogger(__name__)

Intent = Literal["action", "page_info", "search", "direct"]

_CLASSIFIER_SYSTEM = """
ユーザーメッセージの意図を以下の4種類のうち1つに分類し、JSONのみを返してください。説明文は不要です。

- "action": 現在のページ上でクリック・入力・スクロールなど、具体的な操作を代わりに実行してほしい
- "page_info": 現在のページの使い方・操作方法・画面構成・要素について知りたい
- "search": アプリの機能・設定・手順など、ドキュメントを調べる必要がある質問
- "direct": 挨拶・雑談・翻訳・文章生成・要約など、検索不要で直接回答できるもの

返答形式:
{"intent": "action" | "page_info" | "search" | "direct"}
""".strip()


def _parse_intent(text: str) -> Intent | None:
    json_match = re.search(r"\{[^{}]*\}", text)
    if not json_match:
        return None
    try:
        data = json.loads(json_match.group())
        intent = data.get("intent")
        if intent in ("action", "page_info", "search", "direct"):
            return intent
    except (json.JSONDecodeError, AttributeError):
        pass
    return None


def classify_intent(message: str, current_page: str = "") -> Intent:
    """
    ユーザーメッセージの意図をLLMで1回分類して返す。
    失敗時は "direct"（検索なし）にフォールバックする。
    """
    page_line = f"現在のページURL: {current_page}" if current_page else "現在のページ: 不明"
    messages = [
        {"role": "system", "content": _CLASSIFIER_SYSTEM},
        {"role": "user", "content": f"{page_line}\n\nメッセージ: {message}"},
    ]
    try:
        response = get_llm_response(messages, GPT_OSS_20B_LEGACY_MODEL)
        intent = _parse_intent(response or "")
        if intent is not None:
            if not current_page and intent in ("action", "page_info"):
                return "search"
            return intent
    except Exception:
        logger.warning("Intent classification failed, falling back to 'direct'")
    return "direct"
