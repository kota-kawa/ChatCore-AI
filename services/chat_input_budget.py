# 最終回答パスへ送るリクエストの入力量を、送信前に見積もって抑える。
# 長い調査ターンではツール結果が積み上がるため、プロバイダのコンテキスト超過は
# 「内部エラー」としてターンごと失われる。超過してから直すのではなく、送る前に縮める。
# Bounds the request sent to the answer pass. Tool results pile up over a long research
# turn, and a provider context overflow surfaces as a generic internal error that loses the
# whole turn, so shrink the request before sending rather than after it fails.

from __future__ import annotations

import json
import logging
import os
from typing import Any

from services.chat_context import estimate_token_count

logger = logging.getLogger(__name__)

DEFAULT_FINAL_ANSWER_INPUT_TOKEN_BUDGET = 48000
# 圧縮は「本文 → スニペット → 証拠IDのみ」の順に強くする。証拠IDは引用の解決に使うため
# 最後まで残し、どの段階でもモデルが出典を失わないようにする。
# Compaction escalates page text, then snippets, then everything but the evidence IDs. The
# IDs resolve citations, so they survive every level and the model never loses its sources.
_COMPACTION_LEVELS = ("page_text", "snippets", "minimal")
_PRESERVED_TOOL_FIELDS = ("status", "message", "source_count", "cached")
_PRESERVED_SOURCE_FIELDS = ("evidence_id",)
_COMPACTED_TOOL_MESSAGE = (
    "Older evidence was compacted to fit this turn's context. Use the evidence that is still "
    "present and answer from it; do not ask for another search."
)


def get_final_answer_input_token_budget() -> int:
    raw = os.environ.get("LLM_FINAL_ANSWER_INPUT_TOKEN_BUDGET")
    if raw is None:
        return DEFAULT_FINAL_ANSWER_INPUT_TOKEN_BUDGET
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_FINAL_ANSWER_INPUT_TOKEN_BUDGET
    return value if value > 0 else DEFAULT_FINAL_ANSWER_INPUT_TOKEN_BUDGET


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate the request size with the same CJK-aware model as the context budget."""
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += estimate_token_count(content)
        elif content is not None:
            total += estimate_token_count(str(content))
        tool_calls = message.get("tool_calls")
        if tool_calls:
            total += estimate_token_count(json.dumps(tool_calls, ensure_ascii=False))
    return total


def estimate_messages_chars(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        elif content is not None:
            total += len(str(content))
    return total


def _compact_tool_payload(content: str, level: str) -> str | None:
    """Shrink one serialized tool result by one level, or report that it cannot shrink."""
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    sources = payload.get("sources")
    if not isinstance(sources, list):
        return None

    changed = False
    if level == "minimal":
        compacted: dict[str, Any] = {
            key: payload[key] for key in _PRESERVED_TOOL_FIELDS if key in payload
        }
        compacted["status"] = payload.get("status", "completed")
        compacted["message"] = _COMPACTED_TOOL_MESSAGE
        compacted["sources"] = [
            {
                key: source[key]
                for key in _PRESERVED_SOURCE_FIELDS
                if isinstance(source, dict) and key in source
            }
            for source in sources
        ]
        serialized = json.dumps(compacted, ensure_ascii=False)
        return serialized if serialized != content else None

    for source in sources:
        if not isinstance(source, dict):
            continue
        if level == "page_text" and source.get("page_text"):
            source.pop("page_text", None)
            changed = True
        elif level == "snippets" and source.get("snippets"):
            source["snippets"] = []
            changed = True
    if not changed:
        return None
    payload["message"] = _COMPACTED_TOOL_MESSAGE
    return json.dumps(payload, ensure_ascii=False)


def compact_tool_messages(
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
) -> tuple[list[dict[str, Any]], int]:
    """Shrink the oldest tool results until the request fits the input budget.

    古い証拠から順に落とすのは、直近の検索ほど回答に効くため。証拠IDは常に残すので、
    引用マーカーの解決は圧縮後も成立する。
    The oldest evidence is dropped first because later searches matter more to the answer.
    Evidence IDs always survive, so citation-marker resolution still works after compaction.
    """
    if estimate_messages_tokens(messages) <= max_tokens:
        return messages, 0

    compacted = [dict(message) for message in messages]
    tool_indices = [
        index
        for index, message in enumerate(compacted)
        if message.get("role") == "tool" and isinstance(message.get("content"), str)
    ]
    compacted_indices: set[int] = set()
    for level in _COMPACTION_LEVELS:
        for index in tool_indices:
            if estimate_messages_tokens(compacted) <= max_tokens:
                logger.info(
                    "Compacted tool evidence to fit the answer input budget.",
                    extra={
                        "compacted_tool_messages": len(compacted_indices),
                        "max_tokens": max_tokens,
                    },
                )
                return compacted, len(compacted_indices)
            shrunk = _compact_tool_payload(compacted[index]["content"], level)
            if shrunk is None:
                continue
            compacted[index] = {**compacted[index], "content": shrunk}
            compacted_indices.add(index)

    remaining_tokens = estimate_messages_tokens(compacted)
    if remaining_tokens > max_tokens:
        logger.warning(
            "Answer input still exceeds the token budget after compacting every tool result.",
            extra={
                "estimated_tokens": remaining_tokens,
                "max_tokens": max_tokens,
                "compacted_tool_messages": len(compacted_indices),
            },
        )
    return compacted, len(compacted_indices)
