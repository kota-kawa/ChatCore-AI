from __future__ import annotations

import json
import logging
import re
from typing import Literal

from services.agent_capabilities import build_capability_context
from services.llm import GPT_OSS_20B_LEGACY_MODEL, get_llm_response

logger = logging.getLogger(__name__)

Intent = Literal["action", "page_info", "search", "direct"]

_CLASSIFIER_SYSTEM = """
ユーザーメッセージの意図を以下の4種類のうち1つに分類し、JSONのみを返してください。説明文は不要です。

- "action": 現在のページ上でクリック・入力・スクロールなど、具体的な操作を代わりに実行してほしい
- "page_info": 現在のページの使い方・操作方法・画面構成・要素について知りたい
- "search": アプリの機能・設定・手順など、ドキュメントを調べる必要がある質問
- "direct": 挨拶・雑談・翻訳・文章生成・要約など、検索不要で直接回答できるもの

判断ルール:
- 画面を開く、移動する、クリックする、入力する、検索する、設定を切り替える、共有リンクをコピーする等の依頼は "action"
- 「この画面で何ができる」「どこにある」「どう使う」は "page_info"
- アプリ全体の機能説明、手順、仕様確認は "search"
- プロンプト改善、文章作成、要約、翻訳などページ操作を伴わない生成依頼は "direct"

返答形式:
{"intent": "action" | "page_info" | "search" | "direct"}
""".strip()

_ACTION_HINTS = re.compile(
    r"(クリック|タップ|押して|開いて|移動して|表示して|入力して|記入して|検索して|コピーして|共有して|"
    r"保存して|投稿して|削除して|編集して|切り替えて|選択して|スクロールして|実行して|やって|"
    r"代わりに|ページへ|ページに行)",
    re.IGNORECASE,
)

_PAGE_INFO_HINTS = re.compile(
    r"(このページ|この画面|今のページ|今の画面|ここで|どこ|何ができる|使い方|操作方法|"
    r"ボタン|入力欄|フォーム|タブ)",
    re.IGNORECASE,
)

_SEARCH_HINTS = re.compile(
    r"(機能|設定|手順|仕様|できること|方法|Passkey|パスキー|プロンプト共有|メモ|チャットルーム|タスク)",
    re.IGNORECASE,
)

_DIRECT_GENERATION_HINTS = re.compile(
    r"(タイトル案|文章|要約|翻訳|添削|改善|短く|長く|例文|テンプレート|下書き|アイデア)",
    re.IGNORECASE,
)


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
    if _ACTION_HINTS.search(message):
        return "action" if current_page else "search"
    if _PAGE_INFO_HINTS.search(message):
        return "page_info" if current_page else "search"
    if _DIRECT_GENERATION_HINTS.search(message) and not _SEARCH_HINTS.search(message):
        return "direct"

    page_line = f"現在のページURL: {current_page}" if current_page else "現在のページ: 不明"
    capability_context = build_capability_context(current_page)
    messages = [
        {"role": "system", "content": _CLASSIFIER_SYSTEM},
        {
            "role": "user",
            "content": f"{page_line}\n\n{capability_context}\n\nメッセージ: {message}",
        },
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
