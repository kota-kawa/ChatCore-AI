from __future__ import annotations

import json
import logging
import re
from typing import Literal

from services.agent_capabilities import build_capability_context
from services.llm import LIGHTWEIGHT_TASK_MODEL, get_llm_response

logger = logging.getLogger(__name__)

Intent = Literal["action", "page_info", "search", "direct", "unknown"]

# 日本語: ユーザー発話を画面操作・ページ情報・検索・直接回答のいずれかへJSONで分類するシステムプロンプト。
_CLASSIFIER_SYSTEM = """
Classify the intent of the user message into exactly one of the four types below and return JSON only. No explanation is needed.

- "action": the user wants you to carry out a concrete operation on the current page for them, such as clicking, typing, or scrolling
- "page_info": the user wants to know how to use the current page, how to operate it, how it is laid out, or what its elements are
- "search": a question about the app's features, settings, or procedures that requires looking through the documentation
- "direct": greetings, small talk, translation, writing, summarization, and anything else you can answer directly without a search

Decision rules:
- Requests to open a screen, navigate, click, type, search, toggle a setting, copy a share link, and the like are "action"
- "What can I do on this screen", "where is it", and "how do I use it" are "page_info"
- Explanations of the app's overall features, procedures, and specifications are "search"
- Generation requests that involve no page operation, such as improving a prompt, writing text, summarizing, or translating, are "direct"

Response format:
{"intent": "action" | "page_info" | "search" | "direct"}
""".strip()

# LLMの応答テキストからJSONをパースし、分類された意図(Intent)を抽出します。
# Parse JSON from the LLM response text and extract the classified intent.
def _parse_intent(text: str) -> Intent | None:
    json_match = re.search(r"\{[^{}]*\}", text)
    # テキスト内にJSON文字列が見つからない場合は None を返します。
    # Return None if no JSON object is found in the text.
    if not json_match:
        return None
    # JSONのデコードを試み、有効な意図カテゴリに含まれているか検証します。
    # Attempt to decode JSON and validate if it matches one of the valid intent categories.
    try:
        data = json.loads(json_match.group())
        intent = data.get("intent")
        if intent in ("action", "page_info", "search", "direct"):
            return intent
    except (json.JSONDecodeError, AttributeError):
        pass
    return None


# ユーザーメッセージから意図を判定します。意味の分類は常にLLMへ委譲します。
# Classify the user's intent. Semantic classification is always delegated to the LLM.
def classify_intent(message: str, current_page: str = "") -> Intent:
    # ユーザーメッセージの意図をLLMで1回分類して返します。失敗時は "unknown"（操作・検索なし）にフォールバックします。
    # Classifies the user message intent once with the LLM. Falls back to "unknown" (no action or search) on failure.
    """
    ユーザーメッセージの意図をLLMで1回分類して返す。
    失敗時は "unknown"（操作・検索なし）にフォールバックする。
    """
    # ユーザーメッセージとコンテキスト情報（現在のページ、エージェント機能等）を元に、LLMへ送信するプロンプトを構築します。
    # Construct prompt messages to send to the LLM, including user message and context details (current page, capabilities).
    page_line = (
        f"Current page URL: {current_page}" if current_page else "Current page: unknown"
    )
    capability_context = build_capability_context(current_page)
    messages = [
        {"role": "system", "content": _CLASSIFIER_SYSTEM},
        {
            "role": "user",
            "content": f"{page_line}\n\n{capability_context}\n\nMessage: {message}",
        },
    ]
    # LLMにリクエストを送信し、応答テキストをパースして意図を抽出します。
    # Send the request to the LLM and parse the response text to extract the classified intent.
    try:
        response = get_llm_response(messages, LIGHTWEIGHT_TASK_MODEL)
        intent = _parse_intent(response or "")
        if intent is not None:
            if not current_page and intent in ("action", "page_info"):
                return "search"
            return intent
    except Exception:
        logger.warning("Intent classification failed, falling back to 'unknown'")
    return "unknown"
