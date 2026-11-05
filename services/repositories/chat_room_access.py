"""チャットルームの所有者確認とシリアライズを、チャットとプロジェクトの永続化で共有するモジュール。

ルームの移動時にも同じ所有権ルールとロック/エラー契約を使うため、チェックとペイロードをここに一本化している。

Chat room ownership and serialization shared by chat and project persistence.

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

# タイトル未設定のルームに表示する既定名(DB の値は変えず、シリアライズ時にだけ補う)
# Default title for rooms without one (applied only when serializing; the DB value is untouched).
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
    """ルームを取得し、``user_id`` が所有者のときだけ返す。

    不在は ResourceNotFoundError、他人のルームは ``forbidden_message`` 付きの ForbiddenOperationError。
    ``lock=True`` は行ロック(FOR UPDATE)で、移動などの更新前に競合を防ぐ。

    Return the room only when ``user_id`` owns it.

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
    # 履歴一覧とプロジェクト詳細に使うルーム情報へ変換する。
    """Serialize a room row for history lists and project detail payloads."""

    payload: dict[str, Any] = {
        "id": room.id,
        "title": room.title or DEFAULT_CHAT_ROOM_TITLE,
        "mode": room.mode or "normal",
        "created_at": serialize_datetime_iso(room.created_at),
        "last_activity_at": serialize_datetime_iso(room.last_activity_at),
    }
    # 日本語: プロジェクト詳細は camelCase、履歴一覧は snake_case を使う(それぞれの既存フロントの契約に合わせる)。
    # English: Project detail payloads use camelCase while history lists use snake_case, matching each existing frontend contract.
    if project_room:
        payload["createdAt"] = payload.pop("created_at")
        payload["lastActivityAt"] = payload.pop("last_activity_at")
    else:
        # ピン留めはサイドバーの履歴だけが使うので、プロジェクト詳細には載せない。
        # Only the sidebar history uses pins, so project detail payloads leave it out.
        payload["pinned_at"] = serialize_datetime_iso(room.pinned_at)
    return payload
