"""Permanently delete memos whose trash retention period has passed."""

from __future__ import annotations

import logging

from services.repositories.memo_repository import purge_expired_memo_trash

logger = logging.getLogger(__name__)


async def cleanup_expired_memo_trash() -> int:
    """Delete trashed memos older than the retention period, for every user.

    ゴミ箱の保持期間（MEMO_TRASH_RETENTION_DAYS）を過ぎたメモを完全に削除する。共有トークンなどの
    関連行は外部キーの CASCADE で一緒に消える。一覧の取得時には消さず、この定期処理だけが担う。
    Permanently deletes memos past MEMO_TRASH_RETENTION_DAYS; share tokens and other related rows go
    with them through ON DELETE CASCADE. Reads never purge, so this periodic job is the only owner.
    """
    deleted = await purge_expired_memo_trash()
    if deleted:
        logger.info("Permanently deleted %s expired trashed memos.", deleted)
    return deleted
