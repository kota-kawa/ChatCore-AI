"""ContextFactCandidateRepository（自動抽出の保存、自動保存した事実の一覧、候補の承認・却下）が発行する SQL と、
リビジョンによる楽観的排他を検証するテスト。

Tests the SQL emitted by ContextFactCandidateRepository (storing extractions, listing auto-saved facts,
approving and rejecting candidates) and its optimistic revision checks.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects.postgresql import dialect

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
        "importance": 85,
        "confidence": 0.93,
        "fingerprint": "b" * 64,
    }
    row.update(overrides)
    return row


# 日本語: store_extracted が実行する SQL の順(ロック→既存の事実→既存の候補→挿入)に合わせたセッションのモックを作ります。
# English: Build a session mock that follows the order of SQL store_extracted runs (lock, existing facts, existing
# candidates, then inserts).
def _store_session(*, active, pending, facts=(), fingerprint_hit=None, inserts):
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[active, pending] + [fingerprint_hit] * 5)
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(),
            iter(list(facts)),
            iter([]),
            *inserts,
        ]
    )
    return session


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

    async def test_list_auto_saved_in_room_is_owner_scoped_and_escapes_like_wildcards(self):
        session = MagicMock()
        session.execute = AsyncMock(
            return_value=[SimpleNamespace(id=31, title="Rust", revision=2, source_ref="chat:a_b:message:5")]
        )

        rows = await ContextFactCandidateRepository(session).list_auto_saved_in_room(7, "a_b%")

        self.assertEqual(rows, [{"id": 31, "title": "Rust", "revision": 2, "source_ref": "chat:a_b:message:5"}])
        compiled = session.execute.await_args.args[0].compile(dialect=dialect())
        sql = " ".join(str(compiled).split())
        self.assertIn("context_facts.user_id =", sql)
        self.assertIn("context_facts.status =", sql)
        self.assertIn("context_facts.source_kind =", sql)
        self.assertIn("ESCAPE", sql)
        # 候補の承認で作られた事実(本人が見て承認したもの)は通知の対象にしない。
        # Facts created by approving a candidate (reviewed by the owner) are not notified.
        self.assertIn("NOT (EXISTS (SELECT * FROM context_fact_candidates WHERE", sql)
        self.assertIn(7, compiled.params.values())
        like_values = [value for value in compiled.params.values() if isinstance(value, str) and "message:" in value]
        self.assertEqual(len(like_values), 1)
        self.assertNotIn("a_b%", like_values[0])
        self.assertIn("a/_b/%", like_values[0])

    async def test_get_extraction_settings_defaults_to_on_when_no_user_row_exists(self):
        session = MagicMock()
        session.scalar = AsyncMock(side_effect=[None, False, True])
        repo = ContextFactCandidateRepository(session)

        self.assertTrue(await repo.get_extraction_settings(7))
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
