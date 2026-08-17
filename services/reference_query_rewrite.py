"""Rewrite a chat turn into search queries for the user's own saved notes.

The mechanical rewriting this replaces splits on Japanese particles and keeps two-character
runs, which turns "今月は何をしたらいいかな？" into "したらいいか" and "今月" — neither of
which matches anything. A small model reads the turn instead and returns the content words
worth searching for, resolving relative dates on the way.

Only used after a lookup already came back empty, so its cost lands on the turns that need
it rather than on every turn.
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
    "You turn one chat turn into keyword queries for searching the user's own saved notes "
    "(their memos and personal context facts).\n"
    'Reply with JSON only: {"queries": ["...", "..."]}\n'
    "Rules:\n"
    f"- Return 1 to {MAX_REWRITTEN_QUERIES} queries, ordered best first.\n"
    "- Each query is a few space-separated keywords in the language the user wrote in.\n"
    "- Keep only content words. Drop question words, politeness, and demonstratives.\n"
    "- Resolve relative time expressions using today's date, and keep both forms "
    '(for example, with today at 2026-08-18: "今月" becomes "2026年8月 8月").\n'
    "- Add the obvious near-synonyms a note about this topic would plausibly use.\n"
    "- If the turn only makes sense together with the previous turn, take the topic from it.\n"
    "- Never invent facts about the user. Only rephrase what the turn is asking for."
)


def _build_messages(query: str, previous_query: str, now: datetime) -> list[dict[str, Any]]:
    lines = [f"Today's date: {now.strftime('%Y-%m-%d')}"]
    if previous_query:
        lines.append(f"Previous user turn: {previous_query}")
    lines.append(f"Current user turn: {query}")
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
    """Return keyword queries for one turn, or an empty list when the rewrite is unusable."""
    normalized = " ".join(str(query or "").split())
    if not normalized:
        return []

    messages = _build_messages(normalized, previous_query, now or datetime.now().astimezone())
    try:
        raw = get_llm_json_response(messages, LIGHTWEIGHT_TASK_MODEL) or ""
    except Exception:
        # 言い換えは補助にすぎない。失敗しても呼び出し側の既存候補で検索を続ける。
        # The rewrite is only an aid; on failure the caller keeps its own candidates.
        logger.warning("Reference query rewrite failed.", exc_info=True)
        return []

    queries = [candidate for candidate in _parse_queries(raw) if candidate != normalized]
    if not queries:
        logger.info("Reference query rewrite returned nothing usable.")
    return queries
