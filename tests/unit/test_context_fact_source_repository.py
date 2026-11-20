"""ContextFactSourceRepository（記憶の出典行の追加と古い出典の刈り込み）が発行する SQL を検証するテスト。

Tests the SQL emitted by ContextFactSourceRepository, which adds memory source rows and prunes the oldest ones.
"""

import logging
import unittest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.exc import IntegrityError

from services.repositories.context_fact_source_repository import (
    MAX_SOURCES_PER_FACT,
    ContextFactSourceRepository,
)


# 日本語: session.begin_nested() の代わりの SAVEPOINT。中の例外は握りつぶさず、巻き戻したかを記録します。
# English: Stand-in for session.begin_nested(): exceptions inside propagate, and it records whether it rolled back.
class _Savepoint:
    rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.rolled_back = exc_type is not None
        return False


# 日本語: INSERT が行を返したか(scalar_one_or_none)と、事実の行をロックできたか(scalar)だけを差し替えたセッションのモックを作ります。
# English: Build a session mock where only whether the INSERT returned a row (scalar_one_or_none) and whether the fact
# row could be locked (scalar) vary.
def _session(*, inserted_id, locked=12):
    inserted = MagicMock()
    inserted.scalar_one_or_none.return_value = inserted_id
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[inserted, MagicMock()])
    session.scalar = AsyncMock(return_value=locked)
    session.savepoint = _Savepoint()
    session.begin_nested = MagicMock(return_value=session.savepoint)
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
    async def test_new_fact_source_is_inserted_in_a_savepoint_without_a_lock(self):
        session = _session(inserted_id=70)

        await _record(session)

        session.begin_nested.assert_called_once_with()
        session.scalar.assert_not_awaited()
        compiled = session.execute.await_args_list[0].args[0].compile(dialect=dialect())
        self.assertIn("INSERT INTO context_fact_sources", str(compiled))
        self.assertEqual({12, 7, "room-1", 8, "I write a compiler in Rust"}, set(compiled.params.values()))

    async def test_existing_fact_is_locked_for_share_at_the_judged_revision(self):
        session = _session(inserted_id=70)

        await _record(session, expected_revision=3)

        lock = session.scalar.await_args.args[0].compile(dialect=dialect())
        sql = " ".join(str(lock).split())
        self.assertTrue(sql.endswith("FOR SHARE"))
        self.assertIn("context_facts.revision =", sql)
        self.assertIn("context_facts.status =", sql)
        self.assertIn("context_facts.user_id =", sql)
        self.assertEqual({12, 7, 3, "active"}, set(lock.params.values()))
        self.assertEqual(session.execute.await_count, 2)

    async def test_nothing_is_inserted_when_the_fact_is_no_longer_at_that_revision(self):
        session = _session(inserted_id=70, locked=None)

        await _record(session, expected_revision=3)

        session.execute.assert_not_awaited()

    async def test_a_second_source_from_the_same_message_is_dropped_by_the_unique_index(self):
        session = _session(inserted_id=None)

        await _record(session)

        sql = " ".join(str(session.execute.await_args_list[0].args[0].compile(dialect=dialect())).split())
        self.assertIn("ON CONFLICT (fact_id, user_message_id) WHERE user_message_id IS NOT NULL DO NOTHING", sql)
        # 入らなかったときは刈り込みをしない。
        # Nothing is pruned when no row went in.
        self.assertEqual(session.execute.await_count, 1)

    async def test_a_failed_write_rolls_back_only_the_savepoint_and_is_swallowed(self):
        session = _session(inserted_id=70)
        session.execute = AsyncMock(side_effect=IntegrityError("INSERT", {}, Exception("foreign key violation")))

        await _record(session)

        self.assertTrue(session.savepoint.rolled_back)

    async def test_a_failed_write_is_logged_without_the_quote(self):
        # SQLAlchemy の例外の文面には SQL のパラメータ(本人の発話の引用)が入る。例外ごとログに出すと引用が漏れる。
        # SQLAlchemy puts the SQL parameters (the owner's quoted words) in the exception text, so logging the
        # exception would leak the quote.
        quote = "I write a compiler in Rust"
        session = _session(inserted_id=70)
        session.execute = AsyncMock(
            side_effect=IntegrityError("INSERT", {"evidence": quote}, Exception("foreign key violation"))
        )

        with self.assertLogs("services.repositories.context_fact_source_repository", level="INFO") as logs:
            await _record(session, evidence=quote)

        self.assertEqual(len(logs.records), 1)
        record = logs.records[0]
        self.assertIsNone(record.exc_info)
        self.assertEqual((record.fact_id, record.error_type), (12, "IntegrityError"))
        self.assertNotIn(quote, logging.Formatter().format(record))
        self.assertNotIn(quote, str(vars(record)))

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
