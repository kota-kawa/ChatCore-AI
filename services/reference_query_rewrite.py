"""Rewrite a chat turn into search queries for selected chat references.

The query planner reads the latest turn and the previous user turn instead of splitting on
Japanese particles or applying a fixed stop-word list. It returns structured queries that
can be used for memos, My Context facts, and shared prompts, resolving relative dates on the
way.

Only used after a lookup already came back empty, so its cost lands on the turns that need
it rather than on every turn. If the model is unavailable, the caller keeps the original
turn unchanged.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from services.llm import LIGHTWEIGHT_TASK_MODEL, get_llm_json_response

logger = logging.getLogger(__name__)

MAX_REWRITTEN_QUERIES = 2
MAX_REWRITTEN_QUERY_CHARS = 120

_SYSTEM_PROMPT = (
    "You are the selected-reference query planner for a chat turn. Turn the latest user "
    "request into search queries for the explicitly selected sources: the user's memos, "
    "My Context facts, and shared prompts.\n"
    'Reply with JSON only: {"queries": ["...", "..."]}\n'
    "Rules:\n"
    f"- Return 1 to {MAX_REWRITTEN_QUERIES} queries, ordered best first.\n"
    "- Each query is a few space-separated keywords in the language the user wrote in.\n"
    "- Keep only content words. Drop question words, politeness, and demonstratives.\n"
    "- Resolve relative time expressions using today's date, and keep both forms "
    '(for example, with today at 2026-08-18: "今月" becomes "2026年8月 8月").\n'
    "- Add the obvious near-synonyms a note about this topic would plausibly use.\n"
    "- Resolve follow-up wording by understanding the previous user turn; do not copy it "
    "unless it supplies the missing topic.\n"
    "- Never invent facts about the user. Only rephrase what the turn is asking for."
)


def _build_messages(query: str, previous_query: str, now: datetime) -> list[dict[str, Any]]:
    lines = [f"Today's date: {now.strftime('%Y-%m-%d')}"]
    if previous_query:
        lines.append(f"Previous user turn: {previous_query}")
    lines.append(f"Latest user turn: {query}")
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _parse_queries(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        loaded = json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            loaded = json.loads(text[start : end + 1])
        except Exception:
            return []
    if not isinstance(loaded, dict):
        return []

    queries: list[str] = []
    for candidate in loaded.get("queries") or []:
        if not isinstance(candidate, str):
            continue
        normalized = " ".join(candidate.split())[:MAX_REWRITTEN_QUERY_CHARS].strip()
        if normalized and normalized not in queries:
            queries.append(normalized)
        if len(queries) >= MAX_REWRITTEN_QUERIES:
            break
    return queries


def rewrite_reference_query(
    query: str,
    *,
    previous_query: str = "",
    now: datetime | None = None,
) -> list[str]:
    """Return LLM-produced queries, or an empty list when the rewrite is unusable."""
    normalized = " ".join(str(query or "").split())
    if not normalized:
        return []

    messages = _build_messages(normalized, previous_query, now or datetime.now().astimezone())
    try:
        raw = get_llm_json_response(messages, LIGHTWEIGHT_TASK_MODEL) or ""
    except Exception:
        # LLM が使えない場合は呼び出し側が原文だけで検索を続ける。
        # On failure the caller continues with the original turn only.
        logger.warning("Reference query rewrite failed.", exc_info=True)
        return []

    queries = [candidate for candidate in _parse_queries(raw) if candidate != normalized]
    if not queries:
        logger.info("Reference query rewrite returned nothing usable.")
    return queries
