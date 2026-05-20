from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable

from .llm import LlmServiceError, get_llm_response

logger = logging.getLogger(__name__)

CHAT_ROOM_TITLE_MAX_CHARS = 48
CHAT_ROOM_TITLE_LLM_INPUT_CHARS = 1800
DEFAULT_CHAT_ROOM_TITLE = "新規チャット"

_HTML_BR_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def _plain_text(value: str, *, limit: int = CHAT_ROOM_TITLE_LLM_INPUT_CHARS) -> str:
    normalized = _HTML_BR_PATTERN.sub("\n", value or "")
    normalized = _HTML_TAG_PATTERN.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip()


def _sanitize_title(raw_title: str) -> str:
    title = str(raw_title or "").strip()
    if not title:
        return ""

    if title.startswith("{"):
        try:
            payload = json.loads(title)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            title = str(payload.get("title") or "").strip()

    title = title.strip().strip("\"'`「」『』")
    title = re.sub(r"^[#*\-\s]+", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return ""
    return title[:CHAT_ROOM_TITLE_MAX_CHARS].rstrip()


def build_initial_title_candidates(
    user_message: str,
    *,
    task_launch_request: dict[str, str] | None = None,
) -> list[str]:
    candidates = [DEFAULT_CHAT_ROOM_TITLE, user_message[:255].strip()]
    if task_launch_request:
        setup_info = str(task_launch_request.get("setup_info") or "").strip()
        task_name = str(task_launch_request.get("task") or "").strip()
        if setup_info:
            candidates.append(setup_info[:255].strip())
        if task_name:
            candidates.append(task_name[:255].strip())
    return [candidate for candidate in dict.fromkeys(candidates) if candidate]


def generate_chat_room_title(
    user_message: str,
    assistant_response: str,
    model: str,
    *,
    llm_response_getter: Callable[..., str] = get_llm_response,
) -> str:
    user_text = _plain_text(user_message)
    assistant_text = _plain_text(assistant_response)
    if not user_text:
        return ""

    messages = [
        {
            "role": "system",
            "content": (
                "You generate concise chat thread titles. "
                "Return JSON only in the form {\"title\":\"...\"}. "
                "Use the same language as the conversation when possible. "
                f"Keep the title under {CHAT_ROOM_TITLE_MAX_CHARS} characters. "
                "Do not include quotation marks, emojis, markdown, or trailing punctuation."
            ),
        },
        {
            "role": "user",
            "content": "\n".join(
                [
                    "<conversation>",
                    f"<user>{user_text}</user>",
                    f"<assistant>{assistant_text}</assistant>",
                    "</conversation>",
                ]
            ),
        },
    ]

    try:
        raw_title = llm_response_getter(messages, model)
    except LlmServiceError as exc:
        logger.warning("Failed to generate chat room title with LLM: %s", exc)
        return ""
    except Exception:
        logger.exception("Unexpected error while generating chat room title.")
        return ""

    return _sanitize_title(raw_title)


def maybe_auto_title_chat_room(
    *,
    chat_room_id: str,
    user_message: str,
    assistant_response: str,
    model: str,
    allowed_current_titles: list[str],
    conditional_rename: Callable[[str, str, list[str]], bool],
) -> str | None:
    title = generate_chat_room_title(user_message, assistant_response, model)
    if not title:
        return None
    if title in allowed_current_titles:
        return None

    try:
        updated = conditional_rename(chat_room_id, title, allowed_current_titles)
    except Exception:
        logger.exception("Failed to update generated chat room title.")
        return None
    return title if updated else None
