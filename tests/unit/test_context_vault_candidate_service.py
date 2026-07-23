import unittest
from unittest.mock import patch

from services.api_errors import ApiServiceError
from services.context_vault_candidate_service import (
    approve_candidate,
    get_extraction_settings,
    is_context_extraction_enabled,
    list_candidates,
    reject_candidate,
    should_extract_context,
    store_extracted_candidates,
    update_extraction_settings,
)
from services.error_messages import ERROR_CONTEXT_FACT_CANDIDATE_CURSOR_INVALID


def _candidate(**overrides):
    payload = {
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
    payload.update(overrides)
    return payload


def _fact(**overrides):
    payload = {
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
    payload.update(overrides)
    return payload


class ContextVaultCandidateServiceTestCase(unittest.TestCase):
    @patch("services.context_vault_candidate_service._repository")
    def test_store_candidates_requires_opt_in_and_ignores_invalid_items(self, repository_factory):
        repository = repository_factory.return_value
        repository.get_extraction_settings.return_value = False

        self.assertEqual(
            store_extracted_candidates(
                7,
                candidates=[
                    {"fact_type": "project", "title": "Title", "content": "Content"}
                ],
                source_ref="room-123",
            ),
            0,
        )
        repository.store_candidates.assert_not_called()

        repository.get_extraction_settings.return_value = True
        repository.store_candidates.return_value = 1
        inserted = store_extracted_candidates(
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
                {"fact_type": "project", "title": "", "content": "Bad"},
            ],
            source_ref="  room-123  ",
        )

        self.assertEqual(inserted, 1)
        prepared = repository.store_candidates.call_args.args[1]
        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0]["title"], "Chat-Core")
        self.assertEqual(prepared[0]["source_ref"], "room-123")
        self.assertEqual(len(prepared[0]["fingerprint"]), 64)
        self.assertNotIn("internal", prepared[0])

    @patch("services.context_vault_candidate_service._repository")
    def test_fingerprint_is_stable_for_equivalent_normalized_text(self, repository_factory):
        repository = repository_factory.return_value
        repository.get_extraction_settings.return_value = True
        repository.store_candidates.return_value = 2

        store_extracted_candidates(
            7,
            candidates=[
                {"fact_type": "profile", "title": "Ａ  B", "content": "Line  one"},
                {"fact_type": "profile", "title": "a b", "content": "line one"},
            ],
            source_ref="room-123",
        )

        prepared = repository.store_candidates.call_args.args[1]
        self.assertEqual(prepared[0]["fingerprint"], prepared[1]["fingerprint"])

    @patch("services.context_vault_candidate_service._repository")
    def test_list_candidates_uses_cursor_and_allowlists_dto(self, repository_factory):
        repository = repository_factory.return_value
        repository.list_candidates.return_value = [
            _candidate(id=9, created_at="2026-07-23T13:00:00"),
            _candidate(id=8, created_at="2026-07-23T12:00:00"),
            _candidate(id=7, created_at="2026-07-23T11:00:00"),
        ]
        repository.count_pending.return_value = 6

        result = list_candidates(7, limit=2)

        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.next_cursor, "2026-07-23T12:00:00~8")
        self.assertEqual(result.total_pending, 6)
        dumped = result.candidates[0].model_dump()
        self.assertNotIn("user_id", dumped)
        self.assertNotIn("fingerprint", dumped)
        self.assertNotIn("promoted_fact_id", dumped)
        self.assertNotIn("source_client_id", dumped)
        repository.list_candidates.assert_called_once_with(
            7,
            status="pending",
            limit=3,
            before_created_at=None,
            before_id=None,
        )

    @patch("services.context_vault_candidate_service._repository")
    def test_list_candidates_rejects_invalid_cursor(self, repository_factory):
        with self.assertRaises(ApiServiceError) as error:
            list_candidates(7, cursor="invalid")
        self.assertEqual(error.exception.message, ERROR_CONTEXT_FACT_CANDIDATE_CURSOR_INVALID)
        repository_factory.return_value.list_candidates.assert_not_called()

    @patch("services.context_vault_candidate_service.schedule_embedding")
    @patch("services.context_vault_candidate_service._repository")
    def test_approve_schedules_embedding_after_atomic_promotion(
        self,
        repository_factory,
        schedule_embedding,
    ):
        repository = repository_factory.return_value
        repository.approve_candidate.return_value = (
            _candidate(status="approved", revision=2, promoted_fact_id=31),
            _fact(),
        )

        result = approve_candidate(
            7,
            8,
            expected_revision=1,
            title=" Edited title ",
            content=" Edited content ",
            importance=95,
        )

        self.assertEqual(result.fact.id, 31)
        self.assertEqual(result.candidate.status, "approved")
        repository.approve_candidate.assert_called_once_with(
            7,
            8,
            expected_revision=1,
            fact_type=None,
            title="Edited title",
            content="Edited content",
            importance=95,
        )
        schedule_embedding.assert_called_once_with(
            31,
            "project",
            "Edited title",
            "Edited content",
            1,
        )

    @patch("services.context_vault_candidate_service._repository")
    def test_reject_returns_allowlisted_candidate(self, repository_factory):
        repository_factory.return_value.reject_candidate.return_value = _candidate(
            status="rejected",
            revision=2,
        )

        result = reject_candidate(7, 8, expected_revision=1)

        self.assertEqual(result.status, "rejected")
        repository_factory.return_value.reject_candidate.assert_called_once_with(
            7,
            8,
            expected_revision=1,
        )

    @patch("services.context_vault_candidate_service._repository")
    def test_extraction_setting_helpers_delegate_to_repository(self, repository_factory):
        repository = repository_factory.return_value
        repository.get_extraction_settings.return_value = True
        repository.should_extract_context.return_value = False
        repository.update_extraction_settings.return_value = False

        self.assertTrue(is_context_extraction_enabled(7))
        self.assertTrue(get_extraction_settings(7).enabled)
        self.assertFalse(should_extract_context(7))
        self.assertFalse(update_extraction_settings(7, False).enabled)


if __name__ == "__main__":
    unittest.main()
