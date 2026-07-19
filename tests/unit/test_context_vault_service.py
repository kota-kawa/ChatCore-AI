import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from services.api_errors import ApiServiceError
from services.context_vault_service import (
    build_digest,
    create_fact,
    deprecate_fact,
    list_facts,
    search_facts,
    update_fact,
)
from services.request_models import (
    ContextFactCreateRequest,
    ContextFactUpdateRequest,
    McpContextFactUpdateRequest,
)


def fact_row(**overrides):
    row = {
        "id": 3,
        "user_id": 7,
        "fact_type": "preference",
        "title": "Editor",
        "content": "Uses vim keybindings",
        "status": "active",
        "revision": 2,
        "created_at": "2026-07-18T01:00:00",
        "updated_at": "2026-07-18T02:00:00",
        # Internal keyset helper that must never leak through the DTO.
        "_updated_at_raw": "raw-datetime",
    }
    row.update(overrides)
    return row


class ContextFactRequestModelTestCase(unittest.TestCase):
    def test_create_requires_non_blank_fields(self):
        with self.assertRaises(ValidationError):
            ContextFactCreateRequest(fact_type="preference", title=" ", content="x")
        with self.assertRaises(ValidationError):
            ContextFactCreateRequest(fact_type="unknown", title="t", content="c")

    def test_update_requires_revision_and_a_change(self):
        with self.assertRaises(ValidationError):
            ContextFactUpdateRequest(revision=1)
        with self.assertRaises(ValidationError):
            ContextFactUpdateRequest(revision=0, title="t")

    def test_mcp_update_requires_a_changed_field(self):
        with self.assertRaises(ValidationError):
            McpContextFactUpdateRequest(expected_revision=1)


class ContextVaultServiceTestCase(unittest.TestCase):
    def _patch_repo(self, repo):
        return patch("services.context_vault_service._repository", return_value=repo)

    def test_create_schedules_embedding_and_hides_internal_fields(self):
        repo = MagicMock()
        repo.create_fact.return_value = fact_row(revision=1)
        with self._patch_repo(repo), patch(
            "services.context_vault_service.schedule_embedding"
        ) as schedule:
            result = create_fact(7, fact_type="preference", title="Editor", content="Uses vim")

        serialized = result.model_dump()
        self.assertEqual(serialized["id"], 3)
        self.assertEqual(serialized["revision"], 1)
        self.assertNotIn("_updated_at_raw", serialized)
        self.assertNotIn("user_id", serialized)
        schedule.assert_called_once()
        self.assertEqual(schedule.call_args.args[0], 3)

    def test_update_passes_revision_and_reembeds_on_content_change(self):
        repo = MagicMock()
        repo.update_fact.return_value = fact_row(content="new", revision=3)
        with self._patch_repo(repo), patch(
            "services.context_vault_service.schedule_embedding"
        ) as schedule:
            result = update_fact(7, 3, expected_revision=2, content="new")

        self.assertEqual(result.revision, 3)
        self.assertEqual(repo.update_fact.call_args.kwargs["expected_revision"], 2)
        schedule.assert_called_once()

    def test_deprecate_sets_status_and_skips_reembedding(self):
        repo = MagicMock()
        repo.update_fact.return_value = fact_row(status="deprecated", revision=3)
        with self._patch_repo(repo), patch(
            "services.context_vault_service.schedule_embedding"
        ) as schedule:
            result = deprecate_fact(7, 3, expected_revision=2)

        self.assertEqual(result.status, "deprecated")
        self.assertEqual(repo.update_fact.call_args.kwargs["status"], "deprecated")
        schedule.assert_not_called()

    def test_build_digest_groups_orders_and_truncates(self):
        rows = (
            [fact_row(id=i, fact_type="reference") for i in range(1, 4)]
            + [fact_row(id=10, fact_type="profile")]
        )
        repo = MagicMock()
        repo.list_active_for_digest.return_value = rows
        with self._patch_repo(repo):
            digest = build_digest(7, limit_per_type=2)

        # profile group is ordered before reference regardless of insertion order.
        self.assertEqual(digest.groups[0].fact_type, "profile")
        self.assertEqual(digest.groups[1].fact_type, "reference")
        # reference had 3 rows but limit_per_type=2 truncates it.
        self.assertEqual(len(digest.groups[1].facts), 2)
        self.assertTrue(digest.truncated)
        self.assertEqual(digest.facts_total, 3)

    def test_search_uses_semantic_then_falls_back_to_keyword(self):
        repo = MagicMock()
        repo.semantic_search.return_value = []
        repo.text_search.return_value = [fact_row()]
        with self._patch_repo(repo), (
            patch("services.context_vault_service.embeddings_available", return_value=True)
        ), patch("services.context_vault_service.generate_embedding", return_value=[0.1, 0.2]):
            result = search_facts(7, " vim ", mode="semantic")

        repo.semantic_search.assert_called_once()
        repo.text_search.assert_called_once()
        self.assertEqual(result.total, 1)
        self.assertEqual(result.facts[0].title, "Editor")

    def test_search_requires_non_empty_query(self):
        with self.assertRaises(ApiServiceError) as context:
            search_facts(7, "  ")
        self.assertEqual(context.exception.status_code, 400)

    def test_list_returns_next_cursor_when_more_rows_exist(self):
        repo = MagicMock()
        # limit=2 asks the repo for 3; returning 3 signals a next page.
        repo.list_facts.return_value = [fact_row(id=5), fact_row(id=4), fact_row(id=3)]
        repo.count_active.return_value = 9
        with self._patch_repo(repo):
            result = list_facts(7, limit=2)

        self.assertEqual(len(result.facts), 2)
        self.assertEqual(result.total_active, 9)
        self.assertIsNotNone(result.next_cursor)
        self.assertEqual(repo.list_facts.call_args.kwargs["limit"], 3)


if __name__ == "__main__":
    unittest.main()
