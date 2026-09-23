"""Reconcile stored chat images with the messages that still reference them."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from services.chat_image_storage import cleanup_unreferenced_chat_images
from services.db import session_scope
from services.repositories.chat_repository import ChatRepository

logger = logging.getLogger(__name__)

# 画像の保存から発話の保存までの間に消さないための猶予。
# Grace covering the gap between storing an image and storing the message that references it.
CHAT_IMAGE_ORPHAN_GRACE_SECONDS = 60 * 60


async def cleanup_orphaned_chat_images(temporary_room_image_ids: Iterable[str]) -> int:
    """Delete old chat image files referenced neither by stored messages nor temporary rooms.

    ルームや発話を消しても画像ファイルは残るため、プロンプト添付・アバターと同じく
    参照元を正として不要なファイルを消す。一時ルームは DB に行を持たないので、呼び出し側が
    一時ストアの参照を渡す。
    Deleting rooms or messages leaves the files behind, so this reconciles from the referencing
    records like the prompt-attachment and avatar jobs. Temporary rooms have no database rows,
    so the caller passes the ids the temporary store still references.
    """
    async with session_scope() as session:
        referenced = await ChatRepository(session).list_referenced_chat_image_ids()
    referenced.update(temporary_room_image_ids)

    # ファイル照合は blocking I/O だが、DB セッションの外で実行する。
    # File reconciliation is blocking I/O and deliberately runs outside the session.
    deleted = await asyncio.to_thread(
        cleanup_unreferenced_chat_images, referenced, CHAT_IMAGE_ORPHAN_GRACE_SECONDS
    )
    if deleted:
        logger.info("Removed %s unreferenced chat image files.", deleted)
    return deleted
