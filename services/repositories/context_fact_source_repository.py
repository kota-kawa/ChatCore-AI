"""記憶(context_facts)の出典(context_fact_sources)の書き込み。1 行が 1 回の言及(本人の発話の引用・発話・ルーム・時刻)で、
事実ごとに新しい順の上限件数だけ保つ。トランザクションは呼び出し側が持つ。
services/repositories/context_fact_candidate_repository.py から使われる。

Writes the sources (context_fact_sources) of memory facts. One row is one mention (a quote of the owner's words,
its message, room and time), and only the newest MAX_SOURCES_PER_FACT rows are kept per fact.
Transaction ownership stays with the caller; used by services/repositories/context_fact_candidate_repository.py.
"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text, delete, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import ContextFact, ContextFactSource

# 日本語: 1 つの事実に保つ出典の最大件数。超えた分は古いものから消す。
# English: Maximum sources kept per fact; the oldest ones beyond it are deleted.
MAX_SOURCES_PER_FACT = 20


class ContextFactSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # 日本語: 事実に出典を 1 件足し、上限を超えた古い出典を消す。事実の行は更新しない（updated_at・revision を進めない）。
    # 事実が本人のもので有効なときだけ入れ、同じ発話からの二重登録は一意索引で何もせず捨てる。入ったかを返す。
    # English: Add one source to a fact and delete the oldest beyond the cap. The fact row itself is not updated
    # (updated_at and revision stay put). The row goes in only while the fact is the owner's and active, and a second
    # source from the same message is dropped by the unique index. Returns whether a row went in.
    async def record_mention(
        self,
        *,
        fact_id: int,
        user_id: int,
        chat_room_id: str,
        user_message_id: int | None,
        evidence: str,
    ) -> bool:
        # 日本語: INSERT ... SELECT の値は型を明示する（型のない NULL や文字列は PostgreSQL が列の型へ推論できない）。
        # English: The INSERT ... SELECT values carry explicit types, since PostgreSQL cannot infer a bare NULL or string parameter.
        active_owned_fact = select(
            literal(fact_id, Integer),
            literal(user_id, Integer),
            literal(chat_room_id, String),
            literal(user_message_id, Integer),
            literal(evidence, Text),
        ).where(
            select(ContextFact.id)
            .where(
                ContextFact.id == fact_id,
                ContextFact.user_id == user_id,
                ContextFact.status == "active",
            )
            .exists()
        )
        statement = (
            pg_insert(ContextFactSource)
            .from_select(
                ["fact_id", "user_id", "chat_room_id", "user_message_id", "evidence"],
                active_owned_fact,
            )
            .on_conflict_do_nothing(
                index_elements=[ContextFactSource.fact_id, ContextFactSource.user_message_id],
                index_where=ContextFactSource.user_message_id.is_not(None),
            )
            .returning(ContextFactSource.id)
        )
        inserted = (await self.session.execute(statement)).scalar_one_or_none() is not None
        if inserted:
            await self._prune(fact_id)
        return inserted

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
