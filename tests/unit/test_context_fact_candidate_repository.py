import unittest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects.postgresql import dialect

from services.api_errors import ApiServiceError
from services.repositories.context_fact_candidate_repository import (
    ContextFactCandidateRepository,
)


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
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


def _result(*, mapping=None, scalar_rows=None):
    result = MagicMock()
    result.mappings.return_value.first.return_value = mapping
    result.scalars.return_value.all.return_value = scalar_rows or []
    result.scalar_one_or_none.return_value = None
    return result


class ContextFactCandidateRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_store_candidates_uses_user_lock_and_partial_unique_upsert(self):
        session = MagicMock()
        session.scalar = AsyncMock(side_effect=[0, None])
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(),
                _result(scalar_rows=[]),
                _result(scalar_rows=[]),
                _result(),
            ]
        )
        inserted = await ContextFactCandidateRepository(session).store_candidates(
            7,
            [
                {
                    "fact_type": "project",
                    "title": "Rust",
                    "content": "Ongoing compiler project",
                    "fingerprint": "b" * 64,
                }
            ],
        )

        self.assertEqual(inserted, 0)
        lock_sql = str(session.execute.await_args_list[0].args[0].compile(dialect=dialect()))
        self.assertIn("pg_advisory_xact_lock", lock_sql)
        insert_sql = str(session.execute.await_args_list[-1].args[0].compile(dialect=dialect()))
        self.assertIn("ON CONFLICT", insert_sql)
        self.assertIn("RETURNING", insert_sql)

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
