import unittest
from hashlib import sha256
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
    McpContextFactSaveRequest,
    McpContextFactUpdateRequest,
)


def fact_row(**overrides):
    row = {
        "id": 3,
        "user_id": 7,
        "fact_type": "preference",
        "title": "Editor",
        "content": "Uses vim keybindings",
        "source_kind": "manual",
        "source_ref": None,
        "source_client_id": None,
        "importance": 50,
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

    def test_importance_is_bounded_and_counts_as_an_update(self):
        self.assertEqual(
            ContextFactCreateRequest(
                fact_type="preference", title="Editor", content="Vim"
            ).importance,
            50,
        )
        self.assertEqual(ContextFactUpdateRequest(revision=1, importance=0).importance, 0)
        self.assertEqual(
            McpContextFactUpdateRequest(expected_revision=1, importance=100).importance,
            100,
        )
        with self.assertRaises(ValidationError):
            ContextFactCreateRequest(
                fact_type="preference", title="Editor", content="Vim", importance=101
            )

    def test_mcp_idempotency_key_is_limited(self):
        payload = McpContextFactSaveRequest(
            fact_type="preference",
            title="Editor",
            content="Vim",
            idempotency_key="retry-1",
        )
        self.assertEqual(payload.idempotency_key, "retry-1")
        with self.assertRaises(ValidationError):
            McpContextFactSaveRequest(
                fact_type="preference",
                title="Editor",
                content="Vim",
                idempotency_key="x" * 129,
            )


class ContextVaultServiceTestCase(unittest.TestCase):
    def _patch_repo(self, repo):
        return patch("services.context_vault_service._repository", return_value=repo)

    def test_create_schedules_embedding_and_hides_internal_fields(self):
        repo = MagicMock()
        repo.create_fact.return_value = fact_row(
            revision=1,
            source_kind="mcp",
            source_ref="conversation:3",
            source_client_id="cursor",
            importance=80,
        )
        with self._patch_repo(repo), patch(
            "services.context_vault_service.schedule_embedding"
        ) as schedule:
            result = create_fact(
                7,
                fact_type="preference",
                title="Editor",
                content="Uses vim",
                importance=80,
                source_kind="mcp",
                source_ref="conversation:3",
                source_client_id="cursor",
                idempotency_key="retry-1",
            )

        serialized = result.model_dump()
        self.assertEqual(serialized["id"], 3)
        self.assertEqual(serialized["revision"], 1)
        self.assertEqual(serialized["source_kind"], "mcp")
        self.assertEqual(serialized["importance"], 80)
        self.assertNotIn("source_ref", serialized)
        self.assertNotIn("source_client_id", serialized)
        self.assertNotIn("_updated_at_raw", serialized)
        self.assertNotIn("user_id", serialized)
        schedule.assert_called_once()
        self.assertEqual(schedule.call_args.args[0], 3)
        create_kwargs = repo.create_fact.call_args.kwargs
        self.assertEqual(create_kwargs["importance"], 80)
        self.assertEqual(create_kwargs["source_kind"], "mcp")
        self.assertEqual(create_kwargs["source_ref"], "conversation:3")
        self.assertEqual(create_kwargs["source_client_id"], "cursor")
        self.assertEqual(
            create_kwargs["idempotency_key_hash"],
            sha256(b"7\0mcp\0cursor\0retry-1").hexdigest(),
        )
        self.assertEqual(
            create_kwargs["idempotency_payload_hash"],
            sha256(
                b'{"content":"Uses vim","fact_type":"preference","importance":80,'
                b'"source_kind":"mcp","source_ref":"conversation:3","title":"Editor"}'
            ).hexdigest(),
        )

    def test_create_idempotent_replay_skips_embedding(self):
        repo = MagicMock()
        repo.create_fact.return_value = fact_row(_idempotent_replay=True)
        with self._patch_repo(repo), patch(
            "services.context_vault_service.schedule_embedding"
        ) as schedule:
            result = create_fact(
                7,
                fact_type="preference",
                title="Editor",
                content="Uses vim",
                idempotency_key="retry-1",
            )

        self.assertEqual(result.id, 3)
        schedule.assert_not_called()

    def test_update_passes_revision_and_reembeds_on_content_change(self):
        repo = MagicMock()
        repo.update_fact.return_value = fact_row(content="new", revision=3)
        with self._patch_repo(repo), patch(
            "services.context_vault_service.schedule_embedding"
        ) as schedule:
            result = update_fact(7, 3, expected_revision=2, content="new", importance=90)

        self.assertEqual(result.revision, 3)
        self.assertEqual(repo.update_fact.call_args.kwargs["expected_revision"], 2)
        self.assertEqual(repo.update_fact.call_args.kwargs["importance"], 90)
        schedule.assert_called_once()

    def test_active_metadata_update_reembeds_latest_revision(self):
        repo = MagicMock()
        repo.update_fact.return_value = fact_row(importance=90, revision=3)
        with self._patch_repo(repo), patch(
            "services.context_vault_service.schedule_embedding"
        ) as schedule:
            result = update_fact(7, 3, expected_revision=2, importance=90)

        self.assertEqual(result.revision, 3)
        schedule.assert_called_once_with(
            3,
            "preference",
            "Editor",
            "Uses vim keybindings",
            3,
        )

    def test_edit_while_deprecated_then_restore_embeds_latest_snapshot(self):
        repo = MagicMock()
        repo.update_fact.side_effect = [
            fact_row(
                title="Current editor",
                content="Uses Helix",
                status="deprecated",
                revision=3,
            ),
            fact_row(
                title="Current editor",
                content="Uses Helix",
                status="active",
                revision=4,
            ),
        ]
        with self._patch_repo(repo), patch(
            "services.context_vault_service.schedule_embedding"
        ) as schedule:
            deprecated = update_fact(
                7,
                3,
                expected_revision=2,
                title="Current editor",
                content="Uses Helix",
            )
            restored = update_fact(
                7,
                3,
                expected_revision=3,
                status="active",
            )

        self.assertEqual(deprecated.status, "deprecated")
        self.assertEqual(restored.status, "active")
        schedule.assert_called_once_with(
            3,
            "preference",
            "Current editor",
            "Uses Helix",
            4,
        )

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
        self.assertEqual(digest.total_active, 4)
        self.assertEqual(digest.returned_count, 3)
        self.assertEqual(digest.omitted_count, 1)

    def test_build_digest_prioritizes_importance_within_character_budget(self):
        rows = [
            fact_row(id=1, title="high", content="H" * 1_200, importance=90),
            fact_row(id=2, title="low", content="L" * 1_200, importance=10),
        ]
        repo = MagicMock()
        repo.list_active_for_digest.return_value = rows
        with self._patch_repo(repo):
            digest = build_digest(7, max_chars=2_000)

        self.assertEqual(digest.returned_count, 1)
        self.assertEqual(digest.groups[0].facts[0].title, "high")
        self.assertEqual(digest.omitted_count, 1)
        self.assertLessEqual(len(digest.model_dump_json()), 2_000)

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
