"""ContextFactSourceRepository（記憶の出典行の追加と古い出典の刈り込み）が発行する SQL を検証するテスト。

Tests the SQL emitted by ContextFactSourceRepository, which adds memory source rows and prunes the oldest ones.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects.postgresql import dialect

from services.repositories.context_fact_source_repository import (
    MAX_SOURCES_PER_FACT,
    ContextFactSourceRepository,
)


# 日本語: INSERT が行を返したか(scalar_one_or_none)だけを差し替えたセッションのモックを作ります。
# English: Build a session mock where only whether the INSERT returned a row (scalar_one_or_none) varies.
def _session(*, inserted_id):
    inserted = MagicMock()
    inserted.scalar_one_or_none.return_value = inserted_id
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[inserted, MagicMock()])
    return session


def _record(session, **overrides):
    arguments = {
        "fact_id": 12,
        "user_id": 7,
        "chat_room_id": "room-1",
        "user_message_id": 8,
        "evidence": "I write a compiler in Rust",
    }
    arguments.update(overrides)
    return ContextFactSourceRepository(session).record_mention(**arguments)


class ContextFactSourceRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_insert_requires_an_active_fact_of_the_owner(self):
        session = _session(inserted_id=70)

        self.assertTrue(await _record(session))

        compiled = session.execute.await_args_list[0].args[0].compile(dialect=dialect())
        sql = " ".join(str(compiled).split())
        self.assertIn("INSERT INTO context_fact_sources", sql)
        self.assertIn("context_facts.user_id =", sql)
        self.assertIn("context_facts.status =", sql)
        self.assertEqual(
            {12, 7, "room-1", 8, "I write a compiler in Rust", "active"},
            set(compiled.params.values()),
        )

    async def test_a_second_source_from_the_same_message_is_dropped_by_the_unique_index(self):
        session = _session(inserted_id=None)

        self.assertFalse(await _record(session))

        sql = " ".join(str(session.execute.await_args_list[0].args[0].compile(dialect=dialect())).split())
        self.assertIn("ON CONFLICT (fact_id, user_message_id) WHERE user_message_id IS NOT NULL DO NOTHING", sql)
        # 入らなかったときは刈り込みをしない。
        # Nothing is pruned when no row went in.
        self.assertEqual(session.execute.await_count, 1)

    async def test_prune_keeps_only_the_newest_sources_of_the_fact(self):
        session = _session(inserted_id=70)

        await _record(session)

        compiled = session.execute.await_args_list[1].args[0].compile(dialect=dialect())
        sql = " ".join(str(compiled).split())
        self.assertTrue(sql.startswith("DELETE FROM context_fact_sources WHERE context_fact_sources.fact_id ="))
        self.assertIn("NOT IN (SELECT context_fact_sources.id", sql)
        self.assertIn("ORDER BY context_fact_sources.observed_at DESC, context_fact_sources.id DESC", sql)
        self.assertEqual(MAX_SOURCES_PER_FACT, 20)
        self.assertIn(MAX_SOURCES_PER_FACT, compiled.params.values())


if __name__ == "__main__":
    unittest.main()
