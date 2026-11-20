"""記憶(context_facts)の一覧に添える、出典(context_fact_sources)と置き換えの関係の読み取り。記憶の画面の一覧 1 ページぶんの事実を渡すと、
記憶の件数に関係なく定数本の問い合わせで、出典・置き換えた新しい記憶・置き換えた古い記憶をまとめて返す。
書き込みはしない。services/context_vault_service.py の一覧から使われる。

Read-only provenance for a page of the memory screen's list: the sources (context_fact_sources) and the replacement
relations. Given one page of facts it returns the sources, the newer memory that replaced each, and the older memory each
replaced, in a constant number of queries regardless of how many facts the page holds.
Used by the list in services/context_vault_service.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from services.datetime_serialization import serialize_datetime_iso
from services.models import ContextFact, ContextFactSource

# 日本語: 1 つの記憶について一覧に載せる出典の最大件数(新しい順)。
# English: The most sources listed per memory (newest first).
MAX_LISTED_SOURCES_PER_FACT = 3


# 日本語: 1 つの記憶ぶんの出典の件数・最後に話題に出た時刻・新しい順の一部と、置き換えの関係。
# English: One memory's source count, when it was last mentioned, its newest sources and its replacement relations.
@dataclass
class FactProvenance:
    source_count: int = 0
    last_mentioned_at: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    superseded_by: dict[str, Any] | None = None
    replaces: dict[str, Any] | None = None


class ContextFactProvenanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # 日本語: 事実の行(id・status・deprecated_reason を持つ辞書)ごとに、出典と置き換えの関係を返す。キーは事実の id。
    # すべて user_id で絞るので、ほかの利用者の出典・記憶は混ざらない。置き換えの問い合わせは、対象の行があるときだけ流す。
    # English: Per fact row (a dict with id, status and deprecated_reason), the sources and replacement relations, keyed by
    # fact id. Everything is scoped by user_id, so another user's sources and memories never mix in. A replacement query runs
    # only when the page has rows it applies to.
    async def load(self, user_id: int, facts: Sequence[dict[str, Any]]) -> dict[int, FactProvenance]:
        provenance = {int(fact["id"]): FactProvenance() for fact in facts}
        if not provenance:
            return provenance
        await self._load_sources(user_id, provenance)
        replaced_ids = [
            int(fact["id"]) for fact in facts if fact["status"] == "deprecated" and fact["deprecated_reason"] == "superseded"
        ]
        if replaced_ids:
            await self._load_replacements(user_id, provenance, replaced_ids)
        active_ids = [int(fact["id"]) for fact in facts if fact["status"] == "active"]
        if active_ids:
            await self._load_replaced(user_id, provenance, active_ids)
        return provenance

    # 日本語: 出典の件数と最後の時刻は事実ごとの全出典から窓関数で求め、一覧に載せる新しい順の上位だけを行として返す(1 回の問い合わせ)。
    # English: The count and the last time come from all of a fact's sources through window functions, and only the newest few are
    # returned as rows (one query).
    async def _load_sources(self, user_id: int, provenance: dict[int, FactProvenance]) -> None:
        ranked = (
            select(
                ContextFactSource.fact_id.label("fact_id"),
                ContextFactSource.chat_room_id.label("chat_room_id"),
                ContextFactSource.evidence.label("evidence"),
                ContextFactSource.observed_at.label("observed_at"),
                func.row_number()
                .over(
                    partition_by=ContextFactSource.fact_id,
                    order_by=(ContextFactSource.observed_at.desc(), ContextFactSource.id.desc()),
                )
                .label("rank"),
                func.count().over(partition_by=ContextFactSource.fact_id).label("source_count"),
                func.max(ContextFactSource.observed_at).over(partition_by=ContextFactSource.fact_id).label("last_observed_at"),
            )
            .where(ContextFactSource.user_id == user_id, ContextFactSource.fact_id.in_(list(provenance)))
            .subquery()
        )
        result = await self.session.execute(
            select(ranked).where(ranked.c.rank <= MAX_LISTED_SOURCES_PER_FACT).order_by(ranked.c.fact_id, ranked.c.rank)
        )
        for row in result.mappings().all():
            entry = provenance[int(row["fact_id"])]
            entry.source_count = int(row["source_count"])
            entry.last_mentioned_at = serialize_datetime_iso(row["last_observed_at"])
            entry.sources.append(
                {
                    "chat_room_id": str(row["chat_room_id"]),
                    "evidence": str(row["evidence"]),
                    "observed_at": serialize_datetime_iso(row["observed_at"]),
                }
            )

    # 日本語: 置き換えで無効化された記憶に、置き換えた新しい記憶(id・タイトル)を付ける。完全に削除された記憶は参照が外れていて結合に
    # 当たらないので付かない(None のまま)。
    # English: Attaches the newer memory (id and title) to each memory deprecated by replacement. A memory deleted for good has
    # its reference cleared and does not join, so nothing is attached (it stays None).
    async def _load_replacements(self, user_id: int, provenance: dict[int, FactProvenance], replaced_ids: list[int]) -> None:
        replacement = aliased(ContextFact)
        result = await self.session.execute(
            select(ContextFact.id.label("old_id"), replacement.id, replacement.title)
            .join(replacement, replacement.id == ContextFact.superseded_by_fact_id)
            .where(
                ContextFact.user_id == user_id,
                ContextFact.id.in_(replaced_ids),
                ContextFact.status == "deprecated",
                ContextFact.deprecated_reason == "superseded",
                replacement.user_id == user_id,
            )
        )
        for row in result.all():
            provenance[int(row.old_id)].superseded_by = {"id": int(row.id), "title": str(row.title)}

    # 日本語: 有効な記憶ごとに、それが置き換えた直近の古い記憶を付ける。条件は「元に戻す」と同じ(本人の無効化済みで、理由が superseded、
    # 置き換え先がその記憶)。直近は updated_at の新しい順、同じなら id の大きい順。
    # English: Attaches, to each active memory, the most recent older memory it replaced. The condition is the one "undo" uses (the
    # owner's, deprecated, reason superseded, pointing at that memory). Most recent means newest updated_at, then the larger id.
    async def _load_replaced(self, user_id: int, provenance: dict[int, FactProvenance], active_ids: list[int]) -> None:
        result = await self.session.execute(
            select(
                ContextFact.superseded_by_fact_id.label("new_id"),
                ContextFact.id,
                ContextFact.title,
                ContextFact.content,
            )
            .where(
                ContextFact.user_id == user_id,
                ContextFact.status == "deprecated",
                ContextFact.deprecated_reason == "superseded",
                ContextFact.superseded_by_fact_id.in_(active_ids),
            )
            .order_by(ContextFact.superseded_by_fact_id, ContextFact.updated_at.desc(), ContextFact.id.desc())
            .distinct(ContextFact.superseded_by_fact_id)
        )
        for row in result.all():
            provenance[int(row.new_id)].replaces = {"id": int(row.id), "title": str(row.title), "content": str(row.content)}
