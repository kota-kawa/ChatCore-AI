"""部屋の記憶の鮮度（最終言及日と失効）を検証する（issue #781）。

Verifies room-memory freshness: last-mention labels and leaving stale facts out (issue #781).
"""

import asyncio
import unittest
from datetime import datetime
from unittest.mock import patch

from services import chat_state
from services.chat_context import build_memory_system_message
from services.repositories.chat_repository import ChatRepository, RememberedFact


# all() で行を返すだけの DB 結果の代役。
# DB result stand-in that simply returns its rows from all().
class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


# execute に渡された SQL 文を記録し、固定の行を返すセッションの代役。
# Session stand-in that records statements passed to execute and returns fixed rows.
class _CapturingSession:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _FakeResult(self.rows)


# 部屋の記憶の取得が最終言及日で絞り込まれ、ラベル付けされ、日付の扱い方をモデルへ伝えることを検証するテストクラス。
# Test class verifying that room memory is filtered by last mention, labelled with dates, and tells the model how to weigh them.
class RoomMemoryFreshnessTestCase(unittest.TestCase):
    def test_repository_reads_only_facts_mentioned_since_the_cutoff(self):
        mentioned = datetime(2026, 9, 1, 12, 0)
        session = _CapturingSession([("Goで書いている", mentioned)])
        repository = ChatRepository(session)  # type: ignore[arg-type]

        facts = asyncio.run(repository.list_room_memory_facts("room-1", mentioned_since=datetime(2026, 4, 2)))

        self.assertEqual(facts, [RememberedFact("Goで書いている", mentioned)])
        sql = str(session.statements[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("memory_facts.updated_at >= '2026-04-02 00:00:00'", sql)

    def test_facts_are_labelled_with_their_last_mention_and_stale_ones_are_left_out(self):
        captured = {}

        # 呼び出し引数を記録して固定の記憶を返す ChatRepository の代役。
        # ChatRepository stand-in that records its arguments and returns fixed facts.
        class _FakeRepository:
            def __init__(self, _session):
                pass

            async def list_room_memory_facts(self, chat_room_id, *, mentioned_since, limit):
                captured.update(room=chat_room_id, mentioned_since=mentioned_since, limit=limit)
                return [RememberedFact("ユーザーはGoで書いている", datetime(2026, 9, 20, 23, 59))]

        with patch.object(chat_state, "ChatRepository", _FakeRepository):
            facts = asyncio.run(
                chat_state.list_room_memory_facts("room-1", session=object(), now=datetime(2026, 9, 29, 9, 0))
            )

        # 180日より前に最後に言及された事実は読まない。
        # A fact last mentioned more than 180 days ago is not read.
        self.assertEqual(captured["mentioned_since"], datetime(2026, 4, 2, 9, 0))
        self.assertEqual(facts, ["[last mentioned 2026-09-20] ユーザーはGoで書いている"])

    def test_memory_message_tells_the_model_how_to_weigh_the_dates(self):
        message = build_memory_system_message(["[last mentioned 2026-09-20] " + "あ" * 270])

        self.assertIsNotNone(message)
        assert message is not None
        # 長い事実が切り詰められても、先頭の日付は残る。
        # The leading date survives even when a long fact is trimmed.
        self.assertIn("[last mentioned 2026-09-20]", message["content"])
        self.assertIn("the older it is, the more likely it is outdated", message["content"])
        self.assertIn("follow the latest message", message["content"])


if __name__ == "__main__":
    unittest.main()
