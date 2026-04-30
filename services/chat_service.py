import secrets
from typing import Any

from .db import get_db_connection, is_retryable_db_error, rollback_connection
from .repositories.chat_repository import ChatRepository


def _get_chat_repository() -> ChatRepository:
    return ChatRepository(
        connection_getter=get_db_connection,
        retryable_error_checker=is_retryable_db_error,
        rollback=rollback_connection,
        token_generator=secrets.token_urlsafe,
    )


def save_message_to_db(chat_room_id: str, message: str, sender: str) -> int | None:
    return _get_chat_repository().save_message(chat_room_id, message, sender)


def create_chat_room_in_db(room_id: str, user_id: int, title: str, mode: str = "normal") -> None:
    return _get_chat_repository().create_room(room_id, user_id, title, mode)


def delete_chat_room_if_no_assistant_messages(room_id: str, user_id: int) -> bool:
    return _get_chat_repository().delete_room_if_no_assistant_messages(room_id, user_id)


def rename_chat_room_in_db(room_id: str, new_title: str) -> None:
    return _get_chat_repository().rename_room(room_id, new_title)


def get_chat_room_messages(chat_room_id: str) -> list[dict[str, str]]:
    return _get_chat_repository().get_room_messages_for_llm(chat_room_id)


def validate_room_owner(
    room_id: str, user_id: int, forbidden_message: str
) -> str | None:
    return _get_chat_repository().validate_room_owner(room_id, user_id, forbidden_message)


def create_or_get_shared_chat_token(room_id: str, user_id: int) -> str:
    return _get_chat_repository().create_or_get_shared_chat_token(room_id, user_id)


def get_shared_chat_room_payload(
    token: str,
) -> dict[str, Any]:
    return _get_chat_repository().get_shared_chat_room_payload(token)
