"""記憶の画面の一覧に添える出典と置き換えの関係の読み取り(ContextFactProvenanceRepository)の SQL と、結果の詰め替えを検証するテスト。
一覧 1 ページの問い合わせが記憶の件数に比例しないこと、ほかの利用者の行が混ざらない条件になっていることを確かめる。

Tests the SQL and result mapping of the read-only provenance for the memory screen's list (ContextFactProvenanceRepository):
the number of queries does not grow with the page's facts, and every query is scoped to the owner.
"""

import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects.postgresql import dialect

from services.repositories.context_fact_provenance_repository import (
    MAX_LISTED_SOURCES_PER_FACT,
    ContextFactProvenanceRepository,
)
from tests.helpers.sql_helpers import bind_statement_parameters

_NOW = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)


def _sql(statement):
    return " ".join(str(statement.compile(dialect=dialect())).split())


# 日本語: 事実の行（一覧の行と同じく id・status・deprecated_reason を持つ辞書）を作ります。
# English: Build a fact row (id, status and deprecated_reason, like a list row).
def _fact(fact_id, status="active", reason=None):
    return {"id": fact_id, "status": status, "deprecated_reason": reason}


# 日本語: 各問い合わせの結果を順に返すセッションを作ります。mappings().all() と all() の両方を、同じ行の並びで返します。
# English: Build a session returning each query's result in order; both mappings().all() and all() return the same rows.
def _session(*results):
    session = MagicMock()
    prepared = []
    for rows in results:
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        result.all.return_value = rows
        prepared.append(result)
    session.execute = AsyncMock(side_effect=prepared)
    return session


def _source_row(fact_id, room, evidence, *, rank, total, observed=_NOW, last=_NOW):
    return {
        "fact_id": fact_id,
        "chat_room_id": room,
        "evidence": evidence,
        "observed_at": observed,
        "rank": rank,
        "source_count": total,
        "last_observed_at": last,
    }


class ContextFactProvenanceRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_empty_page_runs_no_query(self):
        session = _session()
        self.assertEqual(await ContextFactProvenanceRepository(session).load(7, []), {})
        session.execute.assert_not_awaited()

    async def test_sources_use_window_functions_in_one_owner_scoped_query(self):
        session = _session([_source_row(10, "room-a", "東京に住んでいます", rank=1, total=4)], [])
        provenance = await ContextFactProvenanceRepository(session).load(7, [_fact(10), _fact(11)])

        statement = session.execute.await_args_list[0].args[0]
        sql = _sql(statement)
        self.assertIn("row_number() OVER (PARTITION BY context_fact_sources.fact_id ORDER BY context_fact_sources.observed_at DESC", sql)
        self.assertIn("count(*) OVER (PARTITION BY context_fact_sources.fact_id)", sql)
        self.assertIn("max(context_fact_sources.observed_at) OVER (PARTITION BY context_fact_sources.fact_id)", sql)
        self.assertIn("context_fact_sources.user_id =", sql)
        self.assertIn("context_fact_sources.fact_id IN", sql)
        bound = bind_statement_parameters(statement)
        self.assertIn(7, bound.values())
        self.assertIn(MAX_LISTED_SOURCES_PER_FACT, bound.values())

        first = provenance[10]
        self.assertEqual(first.source_count, 4)
        self.assertEqual(first.last_mentioned_at, _NOW.isoformat())
        self.assertEqual(first.sources, [{"chat_room_id": "room-a", "evidence": "東京に住んでいます", "observed_at": _NOW.isoformat()}])
        # 出典の無い記憶は件数 0・時刻なし。
        # A fact without sources reports zero and no time.
        self.assertEqual((provenance[11].source_count, provenance[11].last_mentioned_at, provenance[11].sources), (0, None, []))

    async def test_keeps_the_newest_sources_in_the_order_returned(self):
        older = datetime(2026, 10, 1, tzinfo=UTC)
        session = _session(
            [
                _source_row(10, "room-b", "新しい引用", rank=1, total=3),
                _source_row(10, "room-a", "古い引用", rank=2, total=3, observed=older),
            ],
            [],
        )
        provenance = await ContextFactProvenanceRepository(session).load(7, [_fact(10)])
        self.assertEqual([source["evidence"] for source in provenance[10].sources], ["新しい引用", "古い引用"])
        self.assertEqual(provenance[10].last_mentioned_at, _NOW.isoformat())

    async def test_query_count_is_constant_whatever_the_page_size(self):
        # 事実が 3 件でも 100 件でも、読み取りは 出典 1・置き換え先 1・置き換えた古い記憶 1 の 3 本以内。
        # Three facts or a hundred, there are at most three reads: sources, the replacing memory and the replaced one.
        for size in (3, 100):
            facts = [_fact(1000 + i, "deprecated", "superseded") for i in range(size // 2)]
            facts += [_fact(2000 + i) for i in range(size - size // 2)]
            session = _session([], [], [])
            await ContextFactProvenanceRepository(session).load(7, facts)
            with self.subTest(size=size):
                self.assertEqual(session.execute.await_count, 3)

    async def test_replacement_queries_run_only_for_the_rows_they_apply_to(self):
        only_active = _session([], [])
        await ContextFactProvenanceRepository(only_active).load(7, [_fact(10)])
        self.assertEqual(only_active.execute.await_count, 2)  # sources + replaced older memory

        only_user_deprecated = _session([])
        await ContextFactProvenanceRepository(only_user_deprecated).load(7, [_fact(10, "deprecated", "user")])
        self.assertEqual(only_user_deprecated.execute.await_count, 1)  # sources only

        only_superseded = _session([], [])
        await ContextFactProvenanceRepository(only_superseded).load(7, [_fact(10, "deprecated", "superseded")])
        self.assertEqual(only_superseded.execute.await_count, 2)  # sources + replacing memory

    async def test_replacing_memory_is_joined_inside_the_owner_and_attached_to_the_replaced_fact(self):
        session = _session([], [MagicMock(old_id=10, id=11, title="新しい住所")])
        provenance = await ContextFactProvenanceRepository(session).load(7, [_fact(10, "deprecated", "superseded")])

        statement = session.execute.await_args_list[1].args[0]
        sql = _sql(statement)
        self.assertIn("JOIN context_facts AS context_facts_1 ON context_facts_1.id = context_facts.superseded_by_fact_id", sql)
        self.assertIn("context_facts.user_id =", sql)
        self.assertIn("context_facts_1.user_id =", sql)
        self.assertIn("context_facts.deprecated_reason =", sql)
        self.assertEqual(provenance[10].superseded_by, {"id": 11, "title": "新しい住所"})

    async def test_a_deleted_replacement_leaves_superseded_by_empty(self):
        # 置き換え先を完全に削除すると外部キーが NULL に戻り、結合に当たらない。
        # Deleting the replacement for good nulls the foreign key, so nothing joins.
        session = _session([], [])
        provenance = await ContextFactProvenanceRepository(session).load(7, [_fact(10, "deprecated", "superseded")])
        self.assertIsNone(provenance[10].superseded_by)

    async def test_replaced_memory_uses_the_same_condition_as_undo_and_picks_the_most_recent(self):
        session = _session([], [MagicMock(new_id=10, id=9, title="旧住所", content="大阪に住んでいる")])
        provenance = await ContextFactProvenanceRepository(session).load(7, [_fact(10)])

        statement = session.execute.await_args_list[1].args[0]
        sql = _sql(statement)
        self.assertIn("DISTINCT ON (context_facts.superseded_by_fact_id)", sql)
        self.assertIn("ORDER BY context_facts.superseded_by_fact_id, context_facts.updated_at DESC, context_facts.id DESC", sql)
        for condition in (
            "context_facts.user_id =",
            "context_facts.status =",
            "context_facts.deprecated_reason =",
            "context_facts.superseded_by_fact_id IN",
        ):
            self.assertIn(condition, sql)
        bound = bind_statement_parameters(statement)
        self.assertIn("deprecated", bound.values())
        self.assertIn("superseded", bound.values())
        self.assertEqual(provenance[10].replaces, {"id": 9, "title": "旧住所", "content": "大阪に住んでいる"})
        self.assertIsNone(provenance[10].superseded_by)


if __name__ == "__main__":
    unittest.main()
