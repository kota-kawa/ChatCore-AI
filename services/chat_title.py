"""チャットルームのタイトルを作る。最初の発話から付く仮タイトルの候補を作る関数と、
LLM で短いタイトルを生成して整える関数を持つ（services/chat_use_case.py が利用）。

Builds chat room titles: the candidates for the provisional title taken from the first message,
and an LLM-generated short title that is cleaned up (used by services/chat_use_case.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from .async_utils import maybe_await
from .chat_post_dependencies import RenameChatRoomIfCurrentTitleIn
from .db import in_transaction_with_retry, session_scope
from .i18n import build_response_language_policy
from .llm import LIGHTWEIGHT_TASK_MODEL, LlmServiceError, get_llm_response
from .repositories.chat_room_access import DEFAULT_CHAT_ROOM_TITLE, get_owned_room_title, rename_room_if_current_title_in

logger = logging.getLogger(__name__)

CHAT_ROOM_TITLE_MAX_CHARS = 48
CHAT_ROOM_TITLE_LLM_INPUT_CHARS = 1800

_HTML_BR_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


# HTMLタグを除去し、余分な空白を正規化した上で、指定文字数に制限した平文テキストを返す
# Remove HTML tags, normalize spacing, and return plain text capped at the character limit
def _plain_text(value: str, *, limit: int = CHAT_ROOM_TITLE_LLM_INPUT_CHARS) -> str:
    normalized = _HTML_BR_PATTERN.sub("\n", value or "")
    normalized = _HTML_TAG_PATTERN.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip()


# タイトル候補からJSONや余分な記号・空白を取り除き、文字数制限をしてクリーンにする
# Clean the title candidate by removing JSON wrappers, quotes, markdown characters, and extra spaces
def _sanitize_title(raw_title: str) -> str:
    title = str(raw_title or "").strip()
    if not title:
        return ""

    if title.startswith("{"):
        try:
            payload = json.loads(title)
        except Exception:
            logger.debug("Chat room title candidate was not valid JSON; using the raw text instead.")
            payload = None
        if isinstance(payload, dict):
            title = str(payload.get("title") or "").strip()

    title = title.strip().strip("\"'`「」『』")
    title = re.sub(r"^[#*\-\s]+", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return ""
    return title[:CHAT_ROOM_TITLE_MAX_CHARS].rstrip()


# ユーザーメッセージやタスク起動リクエスト情報から、初期タイトルの候補リストを構築する
# Build a list of initial chat room title candidates from the user message and task info
def build_initial_title_candidates(
    user_message: str,
    *,
    task_launch_request: dict[str, str] | None = None,
) -> list[str]:
    """改名前に付いていたかもしれないタイトルの候補を返す（既定名、発話の冒頭、タスクの状況設定とタスク名）。
    利用者がまだ名前を変えていないルームだけを自動で改名するため、現在のタイトルがこの中にあるときに限って、
    生成したタイトルへ置き換える（services/chat_use_case.py）。

    Return the titles a room may still carry before the user renames it (default name, start of the message, task setup
    and name).
    The generated title replaces the current one only when it is among these candidates (services/chat_use_case.py).
    """
    candidates = [DEFAULT_CHAT_ROOM_TITLE, user_message[:255].strip()]
    if task_launch_request:
        setup_info = str(task_launch_request.get("setup_info") or "").strip()
        task_name = str(task_launch_request.get("task") or "").strip()
        if setup_info:
            candidates.append(setup_info[:255].strip())
        if task_name:
            candidates.append(task_name[:255].strip())
    return [candidate for candidate in dict.fromkeys(candidates) if candidate]


# LLMを使用して会話内容から簡潔なチャットルームのタイトルを生成する
# Generate a concise chat room title from the conversation content using LLM
def generate_chat_room_title(
    user_message: str,
    assistant_response: str,
    *,
    locale: str = "ja",
    llm_response_getter: Callable[..., str] = get_llm_response,
) -> str:
    """利用者の発話とアシスタントの回答から、軽量モデルに短いタイトルを JSON で生成させ、整えて返す。
    発話が空のときや LLM が失敗したときは空文字列を返す。

    Ask the lightweight model for a short title as JSON and return it cleaned up.
    Returns "" for an empty message or an LLM failure.
    """
    user_text = _plain_text(user_message)
    assistant_text = _plain_text(assistant_response)
    if not user_text:
        return ""

    # 日本語: 会話の依頼部分の言語に合わせ、短いスレッドタイトルだけをJSONで生成させるシステムプロンプト。
    messages = [
        {
            "role": "system",
            "content": (
                "You generate concise chat thread titles. "
                "Return JSON only in the form {\"title\":\"...\"}. "
                "Write the title using this response-language policy:\n"
                f"{build_response_language_policy(locale)}\n"
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
        raw_title = llm_response_getter(messages, LIGHTWEIGHT_TASK_MODEL)
    except LlmServiceError as exc:
        logger.warning("Failed to generate chat room title with LLM: %s", exc)
        return ""
    except Exception:
        logger.exception("Unexpected error while generating chat room title.")
        return ""

    return _sanitize_title(raw_title)


async def generate_and_rename_room(
    *,
    chat_room_id: str,
    user_message: str,
    assistant_response: str,
    allowed_current_titles: list[str],
    user_id: int,
    assistant_message_id: int,
    locale: str,
    generate_title: Callable[..., str],
    rename_room: RenameChatRoomIfCurrentTitleIn,
) -> str | None:
    """新しいタイトルを生成し、保存できた場合だけ返す。Generate a title and return it only if it was persisted."""
    title = await asyncio.to_thread(generate_title, user_message, assistant_response, locale=locale)
    if not title or title in allowed_current_titles:
        return None
    try:
        updated = await maybe_await(
            rename_room(
                chat_room_id, title, allowed_current_titles, user_id=user_id, assistant_message_id=assistant_message_id,
            )
        )
    except Exception:
        logger.exception("Failed to update generated chat room title.")
        return None
    return title if updated else None


async def get_owned_chat_room_title(room_id: str, user_id: int) -> str | None:
    async with session_scope() as session:
        return await get_owned_room_title(session, room_id, user_id)


async def rename_chat_room_if_current_title_in(
    room_id: str,
    new_title: str,
    allowed_current_titles: list[str],
    *,
    user_id: int,
    assistant_message_id: int,
) -> bool:
    async def rename(session: AsyncSession) -> bool:
        return await rename_room_if_current_title_in(
            session, room_id, new_title, allowed_current_titles, user_id=user_id, assistant_message_id=assistant_message_id,
        )

    return await in_transaction_with_retry(None, rename)

