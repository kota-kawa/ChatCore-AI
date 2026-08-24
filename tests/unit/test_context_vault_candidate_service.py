import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.api_errors import ApiServiceError
from services.context_vault_candidate_service import (
    approve_candidate,
    list_candidates,
    reject_candidate,
    store_extracted_candidates,
)
from services.error_messages import ERROR_CONTEXT_FACT_CANDIDATE_CURSOR_INVALID


def _candidate(**overrides):
    row = {
        "id": 8,
        "user_id": 7,
        "fact_type": "project",
        "title": "Chat-Core",
        "content": "Phase 2 candidate",
        "source_kind": "chat",
        "source_ref": "room-123",
        "source_client_id": "internal-client",
        "importance": 80,
        "confidence": 0.9,
        "status": "pending",
        "fingerprint": "a" * 64,
        "promoted_fact_id": None,
        "revision": 1,
        "created_at": "2026-07-23T12:00:00",
        "updated_at": "2026-07-23T12:00:00",
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
        "created_at": "2026-07-23T12:00:00",
        "updated_at": "2026-07-23T12:00:00",
    }
    row.update(overrides)
    return row


def _repo():
    repo = MagicMock()
    for name in (
        "get_extraction_settings",
        "store_candidates",
        "list_candidates",
        "count_pending",
        "approve_candidate",
        "reject_candidate",
    ):
        setattr(repo, name, AsyncMock())
    return repo


class ContextVaultCandidateServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_store_candidates_requires_opt_in_and_normalizes_input(self):
        repo = _repo()
        repo.get_extraction_settings.side_effect = [False, True]
        repo.store_candidates.return_value = 1
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            self.assertEqual(
                await store_extracted_candidates(
                    7,
                    candidates=[{"fact_type": "project", "title": "T", "content": "C"}],
                    source_ref="room-123",
                    session=object(),
                ),
                0,
            )
            inserted = await store_extracted_candidates(
                7,
                candidates=[
                    {
                        "fact_type": "project",
                        "title": "  Chat-Core  ",
                        "content": "  Phase 2  ",
                        "importance": 80,
                        "confidence": 0.9,
                        "internal": "ignored",
                    },
                    {"fact_type": "bogus", "title": "Bad", "content": "Bad"},
                ],
                source_ref="  room-123  ",
                session=object(),
            )
        self.assertEqual(inserted, 1)
        prepared = repo.store_candidates.call_args.args[1]
        self.assertEqual(prepared[0]["title"], "Chat-Core")
        self.assertEqual(prepared[0]["source_ref"], "room-123")
        self.assertEqual(len(prepared[0]["fingerprint"]), 64)

    async def test_list_candidates_returns_cursor_and_allowlisted_dto(self):
        repo = _repo()
        repo.list_candidates.return_value = [
            _candidate(id=9, created_at="2026-07-23T13:00:00"),
            _candidate(id=8, created_at="2026-07-23T12:00:00"),
            _candidate(id=7, created_at="2026-07-23T11:00:00"),
        ]
        repo.count_pending.return_value = 6
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            result = await list_candidates(7, limit=2, session=object())
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.next_cursor, "2026-07-23T12:00:00~8")
        self.assertEqual(result.total_pending, 6)
        self.assertNotIn("fingerprint", result.candidates[0].model_dump())

    async def test_invalid_cursor_is_rejected_before_repository_call(self):
        repo = _repo()
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            with self.assertRaises(ApiServiceError) as error:
                await list_candidates(7, cursor="invalid", session=object())
        self.assertEqual(error.exception.message, ERROR_CONTEXT_FACT_CANDIDATE_CURSOR_INVALID)
        repo.list_candidates.assert_not_awaited()

    async def test_approve_schedules_embedding_only_after_default_transaction(self):
        repo = _repo()
        repo.approve_candidate.return_value = (
            _candidate(status="approved", revision=2, promoted_fact_id=31),
            _fact(),
        )
        with patch("services.context_vault_candidate_service._repository", return_value=repo), patch(
            "services.context_vault_candidate_service.schedule_embedding"
        ) as schedule:
            # Passing a session lets this unit test isolate repository delegation;
            # the route-level default path schedules after its owned transaction.
            result = await approve_candidate(
                7,
                8,
                expected_revision=1,
                title=" Edited title ",
                content=" Edited content ",
                importance=95,
                session=object(),
            )
        self.assertEqual(result.fact.id, 31)
        repo.approve_candidate.assert_awaited_once_with(
            7,
            8,
            expected_revision=1,
            fact_type=None,
            title="Edited title",
            content="Edited content",
            importance=95,
        )
        schedule.assert_not_called()

    async def test_reject_returns_allowlisted_candidate(self):
        repo = _repo()
        repo.reject_candidate.return_value = _candidate(status="rejected", revision=2)
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            result = await reject_candidate(7, 8, expected_revision=1, session=object())
        self.assertEqual(result.status, "rejected")
        repo.reject_candidate.assert_awaited_once_with(7, 8, expected_revision=1)


if __name__ == "__main__":
    unittest.main()
