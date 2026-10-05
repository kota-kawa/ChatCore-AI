"""Permanently delete memos whose trash retention period has passed."""

from __future__ import annotations

import logging

from services.repositories.memo_constants import MEMO_TRASH_PURGE_BATCH_SIZE
from services.repositories.memo_repository import purge_expired_memo_trash

logger = logging.getLogger(__name__)

# 1周期で回すバッチ数の上限。これを超える分は次の周期に回し、1周期の DB 負荷を抑える。
# Cap on batches per cycle; anything beyond it waits for the next cycle to bound the database load.
MAX_PURGE_BATCHES_PER_CYCLE = 10


async def cleanup_expired_memo_trash() -> int:
    """Delete trashed memos older than the retention period, for every user, in bounded batches.

    ゴミ箱の保持期間（MEMO_TRASH_RETENTION_DAYS）を過ぎたメモを完全に削除する。共有トークンなどの
    関連行は外部キーの CASCADE で一緒に消える。一覧の取得時には消さず、この定期処理だけが担う。
    Permanently deletes memos past MEMO_TRASH_RETENTION_DAYS; share tokens and other related rows go
    with them through ON DELETE CASCADE. Reads never purge, so this periodic job is the only owner.
    """
    total = 0
    for _ in range(MAX_PURGE_BATCHES_PER_CYCLE):
        deleted = await purge_expired_memo_trash(limit=MEMO_TRASH_PURGE_BATCH_SIZE)
        total += deleted
        if deleted < MEMO_TRASH_PURGE_BATCH_SIZE:
            break
    if total:
        logger.info("Permanently deleted %s expired trashed memos.", total)
    return total
