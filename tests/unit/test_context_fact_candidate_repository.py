"""ContextFactCandidateRepository（自動抽出の保存、候補の承認・却下）が発行する SQL と、
リビジョンによる楽観的排他を検証するテスト。

Tests the SQL emitted by ContextFactCandidateRepository (storing extractions,
approving and rejecting candidates) and its optimistic revision checks.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.exc import IntegrityError

from services.api_errors import ApiServiceError
from services.repositories.context_fact_candidate_repository import (
    MAX_PENDING_CONTEXT_FACT_CANDIDATES,
    ContextFactCandidateRepository,
)
from services.repositories.context_fact_repository import MAX_ACTIVE_CONTEXT_FACTS


# 日本語: 候補テーブルの 1 行分の辞書を作ります。overrides で項目を差し替えます。
# English: Build one candidate-table row dict; overrides replace individual fields.
def _candidate(**overrides):
    row = {
        "id": 8,
        "user_id": 7,
        "fact_type": "project",
        "title": "Chat-Core",
        "content": "Phase 2 candidate",
        "source_kind": "chat",
        "source_ref": "room-123",
        "source_client_id": None,
        "importance": 80,
        "confidence": 0.9,
        "status": "pending",
        "fingerprint": "a" * 64,
        "promoted_fact_id": None,
        "revision": 1,
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


# 日本語: 事実テーブルの 1 行分の辞書を作ります。
# English: Build one fact-table row dict.
def _fact(**overrides):
    row = {
        "id": 31,
        "user_id": 7,
        "fact_type": "project",
        "title": "Edited title",
        "content": "Edited content",
        "source_kind": "chat",
        "source_ref": "room-123",
        "source_client_id": None,
        "importance": 95,
        "status": "active",
        "revision": 1,
        "confidence": 0.9,
        "last_confirmed_at": None,
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


# 日本語: DB の実行結果を模したモックを作ります。mapping は 1 行取得、scalar_rows は複数行取得の戻り値になります。
# English: Build a mock of a DB execution result; mapping backs single-row reads and scalar_rows backs multi-row
# reads.
def _result(*, mapping=None, scalar_rows=None, inserted_id=None):
    result = MagicMock()
    result.mappings.return_value.first.return_value = mapping
    result.scalars.return_value.all.return_value = scalar_rows or []
    result.scalar_one_or_none.return_value = inserted_id
    return result


# 日本語: 抽出結果 1 件(サービスが検証・正規化した後の形)を作ります。
# English: Build one extraction result in the shape the service hands to the repository.
def _extracted(**overrides):
    row = {
        "fact_type": "project",
        "title": "Rust",
        "content": "Writes a compiler in Rust",
        "source_kind": "chat",
        "source_ref": "chat:room-1:message:9",
        "evidence": "I write a compiler in Rust",
        "importance": 85,
        "confidence": 0.93,
        "fingerprint": "b" * 64,
    }
    row.update(overrides)
    return row


# 日本語: store_extracted が実行する SQL の順(ロック→既存の事実→既存の候補→挿入)に合わせたセッションのモックを作ります。
# English: Build a session mock that follows the order of SQL store_extracted runs (lock, existing facts, existing
# candidates, then inserts).
def _store_session(*, active, pending, facts=(), candidates=(), fingerprint_hit=None, fact_lock=None, inserts):
    # 日本語: session.scalar は文の内容で振り分ける（件数 2 回→重複した事実のロック→fingerprint の照会）。
    # English: session.scalar is answered by statement content (two counts, the lock on a duplicated fact, the fingerprint lookup).
    async def scalar(statement):
        sql = str(statement.compile(dialect=dialect()))
        if "count(context_facts.id)" in sql:
            return active
        if "count(context_fact_candidates.id)" in sql:
            return pending
        if "FOR SHARE" in sql:
            return fact_lock
        return fingerprint_hit

    session = MagicMock()
    session.scalar = AsyncMock(side_effect=scalar)
    session.begin_nested = MagicMock(side_effect=lambda: _Savepoint())
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(),
            iter(list(facts)),
            iter(list(candidates)),
            *inserts,
        ]
    )
    return session


# 日本語: session.begin_nested() の代わりに使う SAVEPOINT。中の例外は握りつぶさず、巻き戻したかを記録します。
# English: Stand-in for session.begin_nested(): exceptions inside propagate, and it records whether it rolled back.
class _Savepoint:
    rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, _exc, _tb):
        self.rolled_back = exc_type is not None
        return False


# 日本語: AsyncSession をモックし、リポジトリが実行する SQL の内容を確認します。
# English: Mock the AsyncSession and inspect the SQL the repository executes.
class ContextFactCandidateRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_store_extracted_saves_unconfirmed_fact_when_active_slot_is_free(self):
        session = _store_session(active=3, pending=0, inserts=[_result(mapping=_fact(id=41, confidence=0.93))])

        stored = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        self.assertEqual(stored.queued_count, 0)
        self.assertEqual([fact["id"] for fact in stored.saved_facts], [41])
        self.assertEqual(stored.saved_facts[0]["last_confirmed_at"], None)
        lock_sql = str(session.execute.await_args_list[0].args[0].compile(dialect=dialect()))
        self.assertIn("pg_advisory_xact_lock", lock_sql)
        insert = session.execute.await_args_list[-1].args[0].compile(dialect=dialect())
        self.assertIn("INSERT INTO context_facts", str(insert))
        # 本人が確かめていないので last_confirmed_at を書かず(NULL)、確信度と出典は抽出時の値を残す。
        # last_confirmed_at is not written (stays NULL); confidence and the source are kept from extraction.
        self.assertNotIn("last_confirmed_at", insert.params)
        self.assertEqual(insert.params["confidence"], 0.93)
        self.assertEqual(insert.params["source_kind"], "chat")
        self.assertEqual(insert.params["source_ref"], "chat:room-1:message:9")

    async def test_store_extracted_queues_only_what_the_active_cap_rejects(self):
        session = _store_session(
            active=MAX_ACTIVE_CONTEXT_FACTS - 1,
            pending=0,
            inserts=[_result(mapping=_fact(id=41)), _result(inserted_id=5)],
        )

        stored = await ContextFactCandidateRepository(session).store_extracted(
            7,
            [_extracted(), _extracted(title="Go", content="Writes services in Go", fingerprint="c" * 64)],
        )

        self.assertEqual(len(stored.saved_facts), 1)
        self.assertEqual(stored.queued_count, 1)
        queue_sql = str(session.execute.await_args_list[-1].args[0].compile(dialect=dialect()))
        self.assertIn("INSERT INTO context_fact_candidates", queue_sql)
        self.assertIn("ON CONFLICT", queue_sql)

    async def test_store_extracted_queues_everything_when_active_facts_are_at_the_cap(self):
        session = _store_session(active=MAX_ACTIVE_CONTEXT_FACTS, pending=0, inserts=[_result(inserted_id=5)])

        stored = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        self.assertEqual(stored.saved_facts, [])
        self.assertEqual(stored.queued_count, 1)

    async def test_store_extracted_stops_when_facts_and_queue_are_both_full(self):
        session = _store_session(
            active=MAX_ACTIVE_CONTEXT_FACTS,
            pending=MAX_PENDING_CONTEXT_FACT_CANDIDATES,
            inserts=[],
        )

        stored = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        self.assertEqual((stored.saved_facts, stored.queued_count), ([], 0))
        self.assertEqual(session.execute.await_count, 1)

    async def test_store_extracted_does_not_save_content_the_owner_already_deprecated(self):
        # 取り消し(deprecated)した事実は重複判定の比較対象に残るので、同じ内容は再び保存されない。
        # A deprecated (undone) fact stays in the duplicate-check corpus, so the same content is not saved again.
        undone = SimpleNamespace(
            id=12,
            revision=3,
            fact_type="project",
            title="Rust",
            content="Writes a compiler in Rust",
            updated_at=None,
            status="deprecated",
        )
        session = _store_session(active=3, pending=0, facts=[undone], inserts=[])

        stored = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        self.assertEqual((stored.saved_facts, stored.queued_count), ([], 0))
        self.assertEqual(session.execute.await_count, 3)
        # 比較対象の事実は状態で絞らない(WHERE に status を含めない)。
        # The facts used for comparison are not filtered by status.
        facts_sql = str(session.execute.await_args_list[1].args[0].compile(dialect=dialect()))
        self.assertNotIn("context_facts.status =", facts_sql.split("WHERE")[1])

    async def test_store_extracted_skips_content_with_an_existing_candidate_fingerprint(self):
        session = _store_session(active=3, pending=0, fingerprint_hit=99, inserts=[])

        stored = await ContextFactCandidateRepository(session).store_extracted(7, [_extracted()])

        self.assertEqual((stored.saved_facts, stored.queued_count), ([], 0))
        self.assertEqual(session.execute.await_count, 3)

    # 日本語: 事実テーブルの 1 行(重複判定の比較対象)を模した行を作ります。
    # English: Build a row standing in for one fact-table row of the duplicate-check corpus.
    @staticmethod
    def _existing_fact(status="active"):
        return SimpleNamespace(
            id=12,
            revision=3,
            fact_type="project",
            title="Rust",
            content="Writes a compiler in Rust",
            updated_at=None,
            status=status,
        )

    @staticmethod
    def _executed_sql(session):
        return [str(call.args[0].compile(dialect=dialect())) for call in session.execute.await_args_list]

    async def test_store_extracted_records_a_source_with_the_saved_fact(self):
        session = _store_session(
            active=3,
            pending=0,
            inserts=[_result(mapping=_fact(id=41)), _result(inserted_id=70), MagicMock()],
        )

        stored = await ContextFactCandidateRepository(session).store_extracted(
            7, [_extracted()], room_id="room-1", user_message_id=8
        )

        self.assertEqual([fact["id"] for fact in stored.saved_facts], [41])
        statements = self._executed_sql(session)
        self.assertIn("INSERT INTO context_facts", statements[3])
        self.assertIn("INSERT INTO context_fact_sources", statements[4])
        self.assertIn("DELETE FROM context_fact_sources", statements[5])
        source_params = session.execute.await_args_list[4].args[0].compile(dialect=dialect()).params
        self.assertEqual(
            {41, 7, "room-1", 8, "I write a compiler in Rust"},
            set(source_params.values()),
        )
        # 同じトランザクションで作った事実なので、ロックも revision の確認もしない。
        # The fact was created in this transaction, so no lock or revision check is needed.
        self.assertFalse(any("FOR SHARE" in str(call.args[0].compile(dialect=dialect())) for call in session.scalar.await_args_list))

    async def test_store_extracted_keeps_no_source_without_a_room_or_evidence(self):
        for room_id, evidence in ((None, "quote"), ("room-1", "")):
            with self.subTest(room_id=room_id, evidence=evidence):
                session = _store_session(active=3, pending=0, inserts=[_result(mapping=_fact(id=41))])

                await ContextFactCandidateRepository(session).store_extracted(
                    7, [_extracted(evidence=evidence)], room_id=room_id, user_message_id=8
                )

                self.assertFalse(any("context_fact_sources" in sql for sql in self._executed_sql(session)))

    async def test_store_extracted_adds_a_source_to_an_active_fact_without_updating_it(self):
        session = _store_session(
            active=3,
            pending=0,
            facts=[self._existing_fact("active")],
            fact_lock=12,
            inserts=[_result(inserted_id=70), MagicMock()],
        )

        stored = await ContextFactCandidateRepository(session).store_extracted(
            7, [_extracted()], room_id="room-1", user_message_id=8
        )

        self.assertEqual((stored.saved_facts, stored.queued_count), ([], 0))
        # 事実の行を FOR SHARE でロックし、重複を判定した時点の revision(3)・有効・本人の条件で確かめてから入れる。
        # The fact row is locked FOR SHARE under the revision read at duplicate time (3), active and owned, before the insert.
        lock = session.scalar.await_args_list[-1].args[0].compile(dialect=dialect())
        self.assertIn("FOR SHARE", str(lock))
        self.assertEqual({12, 7, 3, "active"}, set(lock.params.values()))
        statements = self._executed_sql(session)
        self.assertIn("INSERT INTO context_fact_sources", statements[3])
        self.assertIn("DELETE FROM context_fact_sources", statements[4])
        # 事実の行は更新しない(updated_at・revision を進めない)。
        # The fact row is not updated, so updated_at and revision stay put.
        self.assertFalse(any(sql.startswith(("UPDATE context_facts", "INSERT INTO context_facts")) for sql in statements))
        source_params = session.execute.await_args_list[3].args[0].compile(dialect=dialect()).params
        self.assertIn(12, source_params.values())

    async def test_store_extracted_adds_no_source_when_the_fact_changed_after_the_duplicate_was_judged(self):
        # 更新や無効化は revision を進める。ロックの再評価で revision が合わなければ DB は行を返さず、出典は入らない。
        # An update or deprecation bumps the revision; when the lock's re-check no longer matches, no row comes back and no source goes in.
        session = _store_session(
            active=3,
            pending=0,
            facts=[self._existing_fact("active")],
            fact_lock=None,
            inserts=[],
        )

        stored = await ContextFactCandidateRepository(session).store_extracted(
            7, [_extracted()], room_id="room-1", user_message_id=8
        )

        self.assertEqual((stored.saved_facts, stored.queued_count), ([], 0))
        self.assertEqual(session.execute.await_count, 3)

    async def test_store_extracted_still_saves_the_fact_when_its_source_cannot_be_stored(self):
        # 回答の後の抽出の間にルームが消えると出典の INSERT が外部キー違反になる。事実の保存は巻き戻さず、出典だけ諦める。
        # If the room is deleted while post-reply extraction runs, the source INSERT violates a foreign key; the fact stays saved.
        savepoints = []
        session = _store_session(
            active=3,
            pending=0,
            inserts=[
                _result(mapping=_fact(id=41)),
                IntegrityError("INSERT INTO context_fact_sources", {}, Exception("foreign key violation")),
            ],
        )
        session.begin_nested = MagicMock(side_effect=lambda: savepoints.append(_Savepoint()) or savepoints[-1])

        stored = await ContextFactCandidateRepository(session).store_extracted(
            7, [_extracted()], room_id="gone-room", user_message_id=8
        )

        self.assertEqual([fact["id"] for fact in stored.saved_facts], [41])
        self.assertEqual(len(savepoints), 1)
        self.assertTrue(savepoints[0].rolled_back)
        # 失敗した出典の後に、刈り込みなどを続けない。
        # Nothing more runs after the failed source write.
        self.assertEqual(session.execute.await_count, 5)

    async def test_store_extracted_adds_no_source_when_the_match_is_not_an_active_fact(self):
        pending_candidate = SimpleNamespace(
            fact_type="project",
            title="Rust",
            content="Writes a compiler in Rust",
            updated_at=None,
            status="pending",
        )
        rejected_candidate = SimpleNamespace(
            fact_type="project",
            title="Rust",
            content="Writes a compiler in Rust",
            updated_at=None,
            status="rejected",
        )
        cases = {
            "deprecated fact": {"facts": [self._existing_fact("deprecated")]},
            "pending candidate": {"candidates": [pending_candidate]},
            "rejected candidate": {"candidates": [rejected_candidate]},
        }
        for name, existing in cases.items():
            with self.subTest(name):
                session = _store_session(active=3, pending=0, inserts=[], **existing)

                stored = await ContextFactCandidateRepository(session).store_extracted(
                    7, [_extracted()], room_id="room-1", user_message_id=8
                )

                self.assertEqual((stored.saved_facts, stored.queued_count), ([], 0))
                self.assertEqual(session.execute.await_count, 3)

    async def test_store_extracted_adds_no_source_for_a_duplicate_inside_the_same_batch(self):
        # 同じ発話から同じ内容が 2 件返っても、2 件目は先に保存した事実と重複するだけで出典は二重に入らない。
        # Two identical results from one message: the second matches the first candidate, which has no fact id yet.
        session = _store_session(
            active=3,
            pending=0,
            inserts=[_result(mapping=_fact(id=41)), _result(inserted_id=70), MagicMock()],
        )

        stored = await ContextFactCandidateRepository(session).store_extracted(
            7, [_extracted(), _extracted(fingerprint="c" * 64)], room_id="room-1", user_message_id=8
        )

        self.assertEqual(len(stored.saved_facts), 1)
        sources = [sql for sql in self._executed_sql(session) if sql.startswith("INSERT INTO context_fact_sources")]
        self.assertEqual(len(sources), 1)

    async def test_store_extracted_keeps_no_source_for_candidates_queued_over_the_cap(self):
        session = _store_session(active=MAX_ACTIVE_CONTEXT_FACTS, pending=0, inserts=[_result(inserted_id=5)])

        stored = await ContextFactCandidateRepository(session).store_extracted(
            7, [_extracted()], room_id="room-1", user_message_id=8
        )

        self.assertEqual(stored.queued_count, 1)
        self.assertFalse(any("context_fact_sources" in sql for sql in self._executed_sql(session)))

    async def test_get_extraction_settings_is_disabled_when_the_user_row_cannot_be_read(self):
        # 列は NOT NULL。None は行が読めないときだけなので、有効扱いにせず抽出が走らない側へ倒す。
        # The column is NOT NULL, so None means the row could not be read; it must not count as enabled.
        session = MagicMock()
        session.scalar = AsyncMock(side_effect=[None, False, True])
        repo = ContextFactCandidateRepository(session)

        self.assertFalse(await repo.get_extraction_settings(7))
        self.assertFalse(await repo.get_extraction_settings(7))
        self.assertTrue(await repo.get_extraction_settings(7))

    async def test_should_extract_context_needs_the_setting_and_room_in_facts_or_queue(self):
        for row, expected in (((True, True), True), ((True, False), False), ((False, True), False), (None, False)):
            session = MagicMock()
            session.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=row)))
            self.assertEqual(await ContextFactCandidateRepository(session).should_extract_context(7), expected)
        sql = " ".join(str(session.execute.await_args.args[0].compile(dialect=dialect())).split())
        self.assertIn("context_facts", sql)
        self.assertIn("context_fact_candidates", sql)
        self.assertIn(" OR ", sql)

    async def test_approve_candidate_promotes_fact_and_updates_revision_atomically(self):
        session = MagicMock()
        session.scalar = AsyncMock(side_effect=[_candidate(), 0])
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(),
                _result(mapping=_fact()),
                _result(mapping=_candidate(status="approved", revision=2, promoted_fact_id=31)),
            ]
        )

        candidate, fact = await ContextFactCandidateRepository(session).approve_candidate(
            7,
            8,
            expected_revision=1,
        )

        self.assertEqual(candidate["status"], "approved")
        self.assertEqual(fact["id"], 31)
        fact_sql = str(session.execute.await_args_list[1].args[0].compile(dialect=dialect()))
        candidate_sql = str(session.execute.await_args_list[2].args[0].compile(dialect=dialect()))
        self.assertIn("RETURNING", fact_sql)
        self.assertIn("revision", candidate_sql)

    async def test_approve_candidate_carries_confidence_and_confirms_now(self):
        session = MagicMock()
        session.scalar = AsyncMock(side_effect=[_candidate(confidence=0.72), 0])
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(),
                _result(mapping=_fact(confidence=0.72)),
                _result(mapping=_candidate(status="approved", revision=2, promoted_fact_id=31)),
            ]
        )

        _, fact = await ContextFactCandidateRepository(session).approve_candidate(7, 8, expected_revision=1)

        insert = session.execute.await_args_list[1].args[0]
        compiled = insert.compile(dialect=dialect())
        self.assertEqual(compiled.params["confidence"], 0.72)
        self.assertIn("CURRENT_TIMESTAMP", " ".join(str(compiled).split()))
        self.assertEqual(fact["confidence"], 0.72)

    async def test_approve_candidate_rejects_stale_revision_before_insert(self):
        session = MagicMock()
        session.scalar = AsyncMock(return_value=_candidate(revision=2))
        session.execute = AsyncMock(return_value=MagicMock())

        with self.assertRaises(ApiServiceError):
            await ContextFactCandidateRepository(session).approve_candidate(
                7,
                8,
                expected_revision=1,
            )
        self.assertEqual(session.execute.await_count, 1)

    async def test_reject_candidate_uses_optimistic_revision(self):
        session = MagicMock()
        session.execute = AsyncMock(
            return_value=_result(mapping=_candidate(status="rejected", revision=2))
        )

        candidate = await ContextFactCandidateRepository(session).reject_candidate(
            7,
            8,
            expected_revision=1,
        )

        self.assertEqual(candidate["status"], "rejected")
        sql = str(session.execute.await_args.args[0].compile(dialect=dialect()))
        self.assertIn("revision", sql)
        self.assertIn("RETURNING", sql)


if __name__ == "__main__":
    unittest.main()
