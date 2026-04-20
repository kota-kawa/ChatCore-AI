from __future__ import annotations

import html
import math
import re

_HTML_BR_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
_WHITESPACE_PATTERN = re.compile(r"[ \t]+")
_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")

CONTEXT_TOKEN_BUDGET = 6000
SUMMARY_TOKEN_BUDGET = 900
MEMORY_TOKEN_BUDGET = 500
RECENT_HISTORY_TOKEN_BUDGET = 3400
RECENT_HISTORY_MAX_MESSAGES = 16
ARCHIVE_RECENT_MESSAGE_COUNT = 12
ARCHIVE_SUMMARY_MAX_ITEMS = 4
ARCHIVE_SUMMARY_ITEM_TOKENS = 120


def estimate_token_count(text: str) -> int:
    normalized = text if isinstance(text, str) else str(text)
    if not normalized:
        return 0
    return max(1, math.ceil(len(normalized) / 4))


def normalize_message_text(text: str) -> str:
    normalized = text if isinstance(text, str) else str(text)
    normalized = html.unescape(normalized)
    normalized = _HTML_BR_PATTERN.sub("\n", normalized)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _WHITESPACE_PATTERN.sub(" ", normalized)
    normalized = _BLANK_LINES_PATTERN.sub("\n\n", normalized)
    return normalized.strip()


def trim_text_to_token_budget(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    normalized = normalize_message_text(text)
    if estimate_token_count(normalized) <= max_tokens:
        return normalized

    max_chars = max_tokens * 4
    if max_chars <= 3:
        return normalized[:max_chars]
    return normalized[: max_chars - 3].rstrip() + "..."


def build_room_summary(messages: list[dict[str, str]]) -> tuple[str, int]:
    if len(messages) <= ARCHIVE_RECENT_MESSAGE_COUNT:
        return "", 0

    archived_messages = messages[:-ARCHIVE_RECENT_MESSAGE_COUNT]
    if not archived_messages:
        return "", 0

    first_user_message = ""
    user_points: list[str] = []
    assistant_points: list[str] = []

    for message in archived_messages:
        role = str(message.get("role", "user"))
        content = trim_text_to_token_budget(
            message.get("content", ""),
            ARCHIVE_SUMMARY_ITEM_TOKENS,
        )
        if not content:
            continue

        if role == "user":
            if not first_user_message:
                first_user_message = content
            if content not in user_points:
                user_points.append(content)
        elif role == "assistant" and content not in assistant_points:
            assistant_points.append(content)

    user_points = user_points[-ARCHIVE_SUMMARY_MAX_ITEMS:]
    assistant_points = assistant_points[-ARCHIVE_SUMMARY_MAX_ITEMS:]

    sections: list[str] = ["<conversation_summary>"]
    sections.append(
        f"<archived_message_count>{len(archived_messages)}</archived_message_count>"
    )
    if first_user_message:
        sections.extend(
            [
                "<original_goal>",
                first_user_message,
                "</original_goal>",
            ]
        )
    if user_points:
        sections.append("<user_points>")
        for point in user_points:
            sections.append(f"- {point}")
        sections.append("</user_points>")
    if assistant_points:
        sections.append("<assistant_points>")
        for point in assistant_points:
            sections.append(f"- {point}")
        sections.append("</assistant_points>")
    sections.append(
        "<summary_instruction>上の要約は古い履歴の圧縮情報です。直近メッセージと矛盾する場合は直近メッセージを優先してください。</summary_instruction>"
    )
    sections.append("</conversation_summary>")
    summary = "\n".join(section for section in sections if section).strip()
    return trim_text_to_token_budget(summary, SUMMARY_TOKEN_BUDGET), len(archived_messages)


def select_recent_messages(
    messages: list[dict[str, str]],
    token_budget: int,
    *,
    max_messages: int = RECENT_HISTORY_MAX_MESSAGES,
) -> list[dict[str, str]]:
    if token_budget <= 0:
        return []

    selected_reversed: list[dict[str, str]] = []
    remaining_tokens = token_budget

    for message in reversed(messages):
        normalized_content = normalize_message_text(message.get("content", ""))
        if not normalized_content:
            continue

        if not selected_reversed:
            trimmed_content = trim_text_to_token_budget(normalized_content, remaining_tokens)
            if not trimmed_content:
                continue
            selected_reversed.append(
                {
                    "role": str(message.get("role", "user")),
                    "content": trimmed_content,
                }
            )
            remaining_tokens -= estimate_token_count(trimmed_content)
            continue

        if len(selected_reversed) >= max_messages or remaining_tokens <= 0:
            break

        message_tokens = estimate_token_count(normalized_content)
        if message_tokens > remaining_tokens:
            break

        selected_reversed.append(
            {
                "role": str(message.get("role", "user")),
                "content": normalized_content,
            }
        )
        remaining_tokens -= message_tokens

    return list(reversed(selected_reversed))


def build_summary_system_message(summary_text: str) -> dict[str, str] | None:
    if not summary_text:
        return None
    trimmed = trim_text_to_token_budget(summary_text, SUMMARY_TOKEN_BUDGET)
    if not trimmed:
        return None
    return {
        "role": "system",
        "content": (
            "<archived_context>\n"
            "以下は古い会話履歴の圧縮要約です。事実・制約の引き継ぎに使い、直近ターンより優先しないでください。\n"
            f"{trimmed}\n"
            "</archived_context>"
        ),
    }


def build_memory_system_message(memory_facts: list[str]) -> dict[str, str] | None:
    normalized_facts = [
        trim_text_to_token_budget(fact, 80)
        for fact in memory_facts
        if trim_text_to_token_budget(fact, 80)
    ]
    if not normalized_facts:
        return None

    sections = [
        "<memory_facts>",
        "以下はこの会話で継続的に守るべきユーザー情報または設定です。",
    ]
    for fact in normalized_facts:
        sections.append(f"- {fact}")
    sections.append("</memory_facts>")
    content = "\n".join(sections)
    return {
        "role": "system",
        "content": trim_text_to_token_budget(content, MEMORY_TOKEN_BUDGET),
    }


def build_context_messages(
    *,
    base_system_prompt: str,
    user_profile_prompt: str | None,
    task_prompt: str | None,
    room_summary: str,
    memory_facts: list[str],
    recent_messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": base_system_prompt}]

    if user_profile_prompt:
        messages.append({"role": "system", "content": user_profile_prompt})

    if task_prompt:
        messages.append({"role": "system", "content": task_prompt})

    summary_message = build_summary_system_message(room_summary)
    if summary_message is not None:
        messages.append(summary_message)

    memory_message = build_memory_system_message(memory_facts)
    if memory_message is not None:
        messages.append(memory_message)

    reserved_tokens = sum(
        estimate_token_count(str(message.get("content", "")))
        for message in messages
    )
    remaining_tokens = min(
        CONTEXT_TOKEN_BUDGET - reserved_tokens,
        RECENT_HISTORY_TOKEN_BUDGET,
    )
    if remaining_tokens < 0:
        remaining_tokens = 0

    messages.extend(select_recent_messages(recent_messages, remaining_tokens))
    return messages
