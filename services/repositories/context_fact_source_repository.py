"""記憶(context_facts)の出典(context_fact_sources)の書き込み。1 行が 1 回の言及(本人の発話の引用・発話・ルーム・時刻)で、
事実ごとに新しい順の上限件数だけ保つ。トランザクションは呼び出し側が持つ。
services/repositories/context_fact_candidate_repository.py から使われる。

Writes the sources (context_fact_sources) of memory facts. One row is one mention (a quote of the owner's words,
its message, room and time), and only the newest MAX_SOURCES_PER_FACT rows are kept per fact.
Transaction ownership stays with the caller; used by services/repositories/context_fact_candidate_repository.py.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import ContextFact, ContextFactSource

logger = logging.getLogger(__name__)

# 日本語: 1 つの事実に保つ出典の最大件数。超えた分は古いものから消す。
# English: Maximum sources kept per fact; the oldest ones beyond it are deleted.
MAX_SOURCES_PER_FACT = 20


class ContextFactSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # 日本語: 事実に出典を 1 件足し、上限を超えた古い出典を消す。事実の行は更新しない（updated_at・revision を進めない）。
    # expected_revision を渡すと、その revision の有効な本人の事実の行を FOR SHARE でロックしてから入れる。更新は行ロックを
    # 取るので、重複を判定した後に事実が書き換わった・無効化されたなら、ロックの再評価で revision が合わず何も入れない。
    # 同じトランザクションで作った新しい事実には不要なので None にする。
    # 書き込みは SAVEPOINT の中で行い、外部キー違反（回答後の抽出の間にルームや発話が消えた）などで失敗しても出典だけを諦め、
    # 呼び出し側の事実の保存は巻き戻さない。同じ発話からの二重登録は一意索引で何もせず捨てる。
    # English: Add one source to a fact and delete the oldest beyond the cap. The fact row itself is not updated
    # (updated_at and revision stay put). With expected_revision, the owner's active fact row at that revision is locked
    # FOR SHARE first; an update takes a row lock too, so if the fact was rewritten or deprecated after the duplicate was
    # judged, the lock's re-check no longer matches the revision and nothing is added. A fact created in the same
    # transaction needs no check, so pass None.
    # The write runs in a SAVEPOINT: if it fails (for example a foreign-key violation because the room or message was
    # deleted while extraction ran after the reply), only the source is given up and the caller's fact save is not rolled
    # back. A second source from the same message is dropped by the unique index.
    async def record_mention(
        self,
        *,
        fact_id: int,
        user_id: int,
        chat_room_id: str,
        user_message_id: int | None,
        evidence: str,
        expected_revision: int | None = None,
    ) -> None:
        try:
            async with self.session.begin_nested():
                if expected_revision is not None and not await self._lock_fact(fact_id, user_id, expected_revision):
                    return
                statement = (
                    pg_insert(ContextFactSource)
                    .values(
                        fact_id=fact_id,
                        user_id=user_id,
                        chat_room_id=chat_room_id,
                        user_message_id=user_message_id,
                        evidence=evidence,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[ContextFactSource.fact_id, ContextFactSource.user_message_id],
                        index_where=ContextFactSource.user_message_id.is_not(None),
                    )
                    .returning(ContextFactSource.id)
                )
                if (await self.session.execute(statement)).scalar_one_or_none() is not None:
                    await self._prune(fact_id)
        except (IntegrityError, DataError):
            # 引用の中身はログに出さない（本人の発話）。
            # The quote is the owner's words, so it is not logged.
            logger.info("Skipped a memory source that could not be stored.", extra={"fact_id": fact_id}, exc_info=True)

    async def _lock_fact(self, fact_id: int, user_id: int, revision: int) -> bool:
        locked = await self.session.scalar(
            select(ContextFact.id)
            .where(
                ContextFact.id == fact_id,
                ContextFact.user_id == user_id,
                ContextFact.status == "active",
                ContextFact.revision == revision,
            )
            .with_for_update(read=True)
        )
        return locked is not None

    async def _prune(self, fact_id: int) -> None:
        newest = (
            select(ContextFactSource.id)
            .where(ContextFactSource.fact_id == fact_id)
            .order_by(ContextFactSource.observed_at.desc(), ContextFactSource.id.desc())
            .limit(MAX_SOURCES_PER_FACT)
        )
        await self.session.execute(
            delete(ContextFactSource).where(
                ContextFactSource.fact_id == fact_id,
                ContextFactSource.id.not_in(newest),
            )
        )
