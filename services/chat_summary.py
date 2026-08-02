"""アーカイブ済み会話履歴のLLM要約 / LLM summarization of archived chat history."""

from __future__ import annotations

import logging
import re

from .chat_context import (
    SUMMARY_TOKEN_BUDGET,
    build_room_summary,
    estimate_token_count,
    normalize_message_text,
    render_summary_context,
    select_archived_messages,
    trim_text_to_token_budget,
)
from .llm import LlmServiceError, get_llm_response

logger = logging.getLogger(__name__)

# 要約器へ渡す入力量の上限。これを超える分は各発言を均等に切り詰める。
# Cap on the input handed to the summarizer; longer history is trimmed per message.
SUMMARY_INPUT_TOKEN_BUDGET = 6000
# 要約本文そのものに許す上限。エンベロープ分を残して SUMMARY_TOKEN_BUDGET 未満にする。
# Cap for the summary body itself, leaving room for the XML envelope.
SUMMARY_BODY_TOKEN_BUDGET = max(1, SUMMARY_TOKEN_BUDGET - 200)

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

# 日本語: 古い会話履歴を、後続ターンの回答に必要な事実へ圧縮させる要約用プロンプト。
_SUMMARY_SYSTEM_PROMPT = """
You compress the older part of a chat conversation so the assistant can keep answering accurately after those turns fall out of the context window.

Write the summary as short bullet lines under these exact headings, and omit a heading entirely when it has no content:

GOAL: what the user is ultimately trying to achieve.
DECISIONS: choices, constraints, and requirements that have been settled.
FACTS: concrete values the later turns still need, such as names, versions, numbers, file paths, and identifiers.
OPEN: what is still unresolved or was explicitly deferred.

Rules:
- Record only what actually appears in the conversation. Never invent, generalize, or fill gaps.
- Keep every concrete identifier verbatim; those are the details that cannot be recovered once the history is dropped.
- Drop pleasantries, restated questions, and the assistant's explanatory prose. Keep the outcome, not the wording.
- Write in the language the user writes in.
- Output the bullet lines only. No preamble, no closing remark, no code fences.
""".strip()


def _plain_text(value: str) -> str:
    """Reduce a stored message to plain text for the summarizer."""
    normalized = normalize_message_text(value or "")
    return _HTML_TAG_PATTERN.sub("", normalized).strip()


def _build_summary_input(archived_messages: list[dict[str, str]]) -> str:
    """Render archived messages into a single transcript within the input budget."""
    if not archived_messages:
        return ""

    per_message_budget = max(
        1, SUMMARY_INPUT_TOKEN_BUDGET // max(len(archived_messages), 1)
    )
    lines: list[str] = []
    for message in archived_messages:
        content = _plain_text(str(message.get("content", "")))
        if not content:
            continue
        role = "User" if str(message.get("role", "user")) == "user" else "Assistant"
        lines.append(f"{role}: {trim_text_to_token_budget(content, per_message_budget)}")

    transcript = "\n".join(lines)
    if estimate_token_count(transcript) > SUMMARY_INPUT_TOKEN_BUDGET:
        transcript = trim_text_to_token_budget(transcript, SUMMARY_INPUT_TOKEN_BUDGET)
    return transcript


def _sanitize_summary_body(raw_summary: str) -> str:
    """Strip code fences and stray blank lines from the model's summary."""
    body = str(raw_summary or "").strip()
    if not body:
        return ""

    # モデルがコードフェンスで包んだ場合に備えて取り除く
    # Remove a wrapping code fence if the model added one
    if body.startswith("```"):
        lines = [line for line in body.splitlines() if not line.strip().startswith("```")]
        body = "\n".join(lines).strip()

    lines = [line.rstrip() for line in body.splitlines() if line.strip()]
    if not lines:
        return ""
    return trim_text_to_token_budget("\n".join(lines), SUMMARY_BODY_TOKEN_BUDGET)


def summarize_archived_messages(
    archived_messages: list[dict[str, str]],
    *,
    model: str,
) -> str:
    """Summarize archived messages with the conversation's model, or "" on failure."""
    transcript = _build_summary_input(archived_messages)
    if not transcript:
        return ""

    try:
        raw_summary = get_llm_response(
            [
                {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "<conversation_to_compress>\n"
                        f"{transcript}\n"
                        "</conversation_to_compress>"
                    ),
                },
            ],
            model,
        )
    except LlmServiceError:
        logger.warning(
            "Failed to summarize archived chat history; falling back to the excerpt summary.",
            exc_info=True,
        )
        return ""
    except Exception:
        logger.exception("Unexpected error while summarizing archived chat history.")
        return ""

    return _sanitize_summary_body(raw_summary)


# 会話履歴からルーム要約を構築する。要約は会話で選択中のモデルに任せ、
# モデル未指定または失敗時は決定的な抜粋方式へフォールバックする。
# Build the room summary from history using the conversation's own model, and
# fall back to the deterministic excerpt summary when no model is available or
# the call fails.
def build_room_summary_text(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
) -> tuple[str, int]:
    archived_messages = select_archived_messages(messages)
    if not archived_messages:
        return "", 0

    summary_body = (
        summarize_archived_messages(archived_messages, model=model) if model else ""
    )
    if not summary_body:
        return build_room_summary(messages)

    return (
        render_summary_context([summary_body], len(archived_messages)),
        len(archived_messages),
    )
