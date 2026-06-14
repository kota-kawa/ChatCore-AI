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


# 日本語: plain text に関する処理の入口です。
# English: Entry point for logic related to plain text.
def _plain_text(value: str, *, limit: int = CHAT_ROOM_TITLE_LLM_INPUT_CHARS) -> str:
    normalized = _HTML_BR_PATTERN.sub("\n", value or "")
    normalized = _HTML_TAG_PATTERN.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip()


# 日本語: sanitize title に関する処理の入口です。
# English: Entry point for logic related to sanitize title.
def _sanitize_title(raw_title: str) -> str:
    title = str(raw_title or "").strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not title:
        return ""

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
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


# 日本語: build initial title candidates の組み立て処理を担当します。
# English: Handle building for build initial title candidates.
def build_initial_title_candidates(
    user_message: str,
    *,
    task_launch_request: dict[str, str] | None = None,
) -> list[str]:
    candidates = [DEFAULT_CHAT_ROOM_TITLE, user_message[:255].strip()]
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if task_launch_request:
        setup_info = str(task_launch_request.get("setup_info") or "").strip()
        task_name = str(task_launch_request.get("task") or "").strip()
        if setup_info:
            candidates.append(setup_info[:255].strip())
        if task_name:
            candidates.append(task_name[:255].strip())
    return [candidate for candidate in dict.fromkeys(candidates) if candidate]


# 日本語: generate chat room title の生成処理を担当します。
# English: Handle generating for generate chat room title.
def generate_chat_room_title(
    user_message: str,
    assistant_response: str,
    model: str,
    *,
    llm_response_getter: Callable[..., str] = get_llm_response,
) -> str:
    user_text = _plain_text(user_message)
    assistant_text = _plain_text(assistant_response)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
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

    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        raw_title = llm_response_getter(messages, model)
    except LlmServiceError as exc:
        logger.warning("Failed to generate chat room title with LLM: %s", exc)
        return ""
    except Exception:
        logger.exception("Unexpected error while generating chat room title.")
        return ""

    return _sanitize_title(raw_title)


# 日本語: maybe auto title chat room に関する処理の入口です。
# English: Entry point for logic related to maybe auto title chat room.
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
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not title:
        return None
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if title in allowed_current_titles:
        return None

    try:
        updated = conditional_rename(chat_room_id, title, allowed_current_titles)
    except Exception:
        logger.exception("Failed to update generated chat room title.")
        return None
    return title if updated else None
