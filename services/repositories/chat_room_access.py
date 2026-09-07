"""Chat room ownership and serialization shared by chat and project persistence.

``chat_rooms`` rows are owned by :class:`~services.repositories.chat_repository.ChatRepository`,
but project persistence also has to verify the same ownership rules when a room
is moved into or out of a project.  Keeping the check and the room payload in
one module avoids duplicating the locking and error contract in both
repositories.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.datetime_serialization import serialize_datetime_iso
from services.error_messages import ERROR_CHAT_ROOM_FORBIDDEN, ERROR_CHAT_ROOM_NOT_FOUND
from services.models import ChatRoom

__all__ = [
    "DEFAULT_CHAT_ROOM_TITLE",
    "ERROR_CHAT_ROOM_FORBIDDEN",
    "load_owned_room",
    "serialize_room",
]

DEFAULT_CHAT_ROOM_TITLE = "新規チャット"


async def load_owned_room(
    session: AsyncSession,
    room_id: str,
    user_id: int,
    forbidden_message: str,
    *,
    lock: bool = False,
    forbidden_returns_false: bool = False,
) -> ChatRoom | None:
    """Return the room only when ``user_id`` owns it.

    ``forbidden_returns_false`` lets callers that report a boolean outcome skip
    the exception contract without re-implementing the lookup.
    """

    statement = select(ChatRoom).where(ChatRoom.id == room_id)
    if lock:
        statement = statement.with_for_update()
    room = (await session.execute(statement)).scalar_one_or_none()
    if room is None:
        if forbidden_returns_false:
            return None
        raise ResourceNotFoundError(ERROR_CHAT_ROOM_NOT_FOUND)
    if room.user_id != user_id:
        if forbidden_returns_false:
            return None
        raise ForbiddenOperationError(forbidden_message)
    return room


def serialize_room(room: ChatRoom, *, project_room: bool = False) -> dict[str, Any]:
    """Serialize a room row for history lists and project detail payloads."""

    payload: dict[str, Any] = {
        "id": room.id,
        "title": room.title or DEFAULT_CHAT_ROOM_TITLE,
        "mode": room.mode or "normal",
        "created_at": serialize_datetime_iso(room.created_at),
        "last_activity_at": serialize_datetime_iso(room.last_activity_at),
    }
    if project_room:
        payload["createdAt"] = payload.pop("created_at")
        payload["lastActivityAt"] = payload.pop("last_activity_at")
    return payload
