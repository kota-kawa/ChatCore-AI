"""Reconcile stored avatar files with the URLs users still reference."""

from __future__ import annotations

import asyncio
import logging

from services.avatar_storage import cleanup_unreferenced_avatars
from services.db import session_scope
from services.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


async def cleanup_orphaned_avatars() -> int:
    """Delete old avatar files no user row references any more.

    プロフィール更新は毎回新しいファイル名で保存するため、置き換えられた古い
    ファイルが保存先に残り続ける。プロンプト添付の照合ジョブと同じく DB を正と
    して不要ファイルを削除する。
    English: Each profile update writes a new filename, so replaced files pile
    up. This mirrors the prompt-attachment reconciler and deletes from database
    truth.
    """
    async with session_scope() as session:
        avatar_urls = await UserRepository(session).list_active_avatar_urls()

    # ファイル照合は blocking I/O だが、DB セッションの外で実行する。
    # File reconciliation is blocking I/O and deliberately runs outside the session.
    deleted = await asyncio.to_thread(cleanup_unreferenced_avatars, avatar_urls)
    if deleted:
        logger.info("Removed %s unreferenced avatar files.", deleted)
    return deleted
