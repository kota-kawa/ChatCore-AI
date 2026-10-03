"""モデルが返したツール呼び出しの解析・整形と、ツールが外部の内容を読んだかの判定。

Parses and shapes the tool calls a model returns, and decides whether a tool read external content.

生成ループの各フェーズが共有する純粋関数だけを置く。ツールの実行と状態の更新は
`ChatGenerationJob` 側が持つ。
Only pure functions shared by the generation loop's phases live here; running the tools and
updating the turn state stay with `ChatGenerationJob`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .chat_web_page_reader import READ_WEB_PAGE_TOOL_NAME
from .chat_workspace_tools.profile import PROFILE_TOOL_FAMILY
from .chat_workspace_tools.prompts import (
    PROMPTS_TOOL_FAMILY,
    SHARED_PROMPT_READ_TOOL_NAME,
)
from .selected_reference_context import PERSONAL_KNOWLEDGE_SOURCE
from .shared_prompt_lookup import SHARED_PROMPT_TOOL_NAME

logger = logging.getLogger(__name__)


def _contains_unconfirmed_context_facts(payload: dict[str, Any] | None) -> bool:
    """Whether a personal-knowledge result contains facts the owner has not confirmed."""
    if not payload:
        return False
    facts = payload.get("context_facts")
    if not isinstance(facts, list):
        return False
    return any(not isinstance(fact, dict) or fact.get("confirmed") is not True for fact in facts)


def _is_memo_only_request(latest_user_message: str) -> bool:
    """Whether this memo-related request lacks an explicit external lookup request."""
    request = re.sub(r"```.*?```", "", latest_user_message, flags=re.DOTALL)
    request = re.sub(r'「[^」]*」|『[^』]*』|"[^"]*"|“[^”]*”|`[^`]*`', "", request)
    request = request.casefold()
    if "メモ" not in request and not re.search(r"\b(?:memo|notes?)\b", request):
        return False
    external_request_markers = (
        "web search", "search the web", "browse the web", "internet", "online", "external information",
        "public sources", "current price", "current weather", "latest news", "today's weather",
        "web検索", "ウェブ検索", "インターネット", "ネットで", "外部情報", "最新のニュース",
        "最新の価格", "今日の天気", "現在の価格", "現在の天気", "出典", "引用",
    )
    return not any(marker in request for marker in external_request_markers)


# 外部の内容を読むツール。呼んだターンでは「常に承認」でも書き込みを自動では実行しない。
# shared_prompt_read も他人の公開投稿を読むため同じ扱いにする。
# Tools that read external content; a turn that calls one never runs writes on its own, even
# under "always approve". shared_prompt_read reads another user's public post, so it counts too.
_EXTERNAL_CONTENT_TOOL_NAMES = frozenset(
    {"web_search", READ_WEB_PAGE_TOOL_NAME, SHARED_PROMPT_TOOL_NAME, SHARED_PROMPT_READ_TOOL_NAME}
)
# 利用者自身のデータの根拠。get_evidence でこれ以外を読み直したら外部の内容を読んだとみなす。
# prompts は自分用プロンプト（Task）・個人Skill の一覧で、shared_prompts（公開投稿）は含まない。
# Evidence from the user's own data; re-reading anything else through get_evidence counts as
# reading external content. prompts covers the user's own Task/Skill listings; shared_prompts
# (public posts) is deliberately excluded.
_OWN_DATA_EVIDENCE_TYPES = frozenset(
    {"memo", PERSONAL_KNOWLEDGE_SOURCE, PROMPTS_TOOL_FAMILY, PROFILE_TOOL_FAMILY}
)


def _includes_external_evidence(payload: dict[str, Any]) -> bool:
    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        return False
    return any(
        isinstance(record, dict) and record.get("source_type") not in _OWN_DATA_EVIDENCE_TYPES
        for record in evidence
    )


# ストリームのチャンク文字列からツール呼び出し（JSON形式）を解析する
# Parse tool calls (JSON format) from a stream chunk string
def _parse_tool_calls_chunk(chunk: str) -> list[dict[str, Any]] | None:
    stripped = chunk.strip()
    if not stripped.startswith("[") or '"function"' not in stripped:
        return None
    try:
        loaded = json.loads(stripped)
    except Exception:
        # 日本語: モデルがツール呼び出し風のテキストを壊れた JSON で返した場合。通常の本文として扱います。
        # English: The model returned tool-call-looking text as broken JSON; treat it as ordinary content.
        logger.debug("Discarded malformed tool-call JSON from the model response.", exc_info=True)
        return None
    if not isinstance(loaded, list):
        return None
    tool_calls: list[dict[str, Any]] = []
    for item in loaded:
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        if not function.get("name"):
            continue
        tool_calls.append(item)
    return tool_calls or None


# ツール引数として渡されたテキストを、型が揺れていても安全に文字列へ寄せる
# Coerce a tool argument into text, tolerating whatever type the model produced
# スキーマ検証をプロバイダに任せない以上、引数の型はこちらで受け止める。文字列以外
# （数値・文字列の配列など）でも実行を止めず、解釈できない値だけを空文字にする。
# Since provider-side schema validation is no longer relied upon, the argument types are
# absorbed here. Non-strings (numbers, a list of strings) still run; only values that
# cannot be read at all become an empty string.
def _tool_argument_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return " ".join(_tool_argument_text(entry) for entry in value).strip()
    return ""


# ツール呼び出しオブジェクトに必要なIDやデフォルト値などを設定して正規化する
# Normalize a tool call object by setting required IDs and default values
def _normalize_tool_call(tool_call: dict[str, Any], *, step: int, index: int) -> dict[str, Any]:
    normalized = dict(tool_call)
    function = dict(normalized.get("function") or {})
    normalized["function"] = function
    normalized["type"] = normalized.get("type") or "function"
    normalized["id"] = str(normalized.get("id") or f"call-{step}-{index}")
    function["name"] = str(function.get("name") or "")
    function["arguments"] = str(function.get("arguments") or "{}")
    return normalized


# ツール実行結果を表すメッセージオブジェクトを構築する
# Construct a message object representing the tool execution result
def _tool_result_message(tool_call: dict[str, Any], content: dict[str, Any] | str) -> dict[str, Any]:
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return {
        "role": "tool",
        "tool_call_id": tool_call.get("id"),
        "name": tool_call.get("function", {}).get("name", ""),
        "content": content,
    }
