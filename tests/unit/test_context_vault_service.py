import unittest
from hashlib import sha256
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from services.api_errors import ApiServiceError
from services.context_vault_service import (
    build_digest,
    create_fact,
    list_facts,
    search_facts,
    update_fact,
)
from services.request_models import (
    ContextFactCreateRequest,
    ContextFactUpdateRequest,
    McpContextFactSaveRequest,
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
    }
    row.update(overrides)
    return row


class _TransactionSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def begin(self):
        return self


def _repo():
    repo = MagicMock()
    for name in (
        "create_fact",
        "update_fact",
        "get_fact",
        "list_facts",
        "count_active",
        "list_active_for_digest",
        "semantic_search",
        "text_search",
    ):
        setattr(repo, name, AsyncMock())
    return repo


class ContextFactRequestModelTestCase(unittest.TestCase):
    def test_create_and_update_requests_validate_contracts(self):
        with self.assertRaises(ValidationError):
            ContextFactCreateRequest(fact_type="preference", title=" ", content="x")
        with self.assertRaises(ValidationError):
            ContextFactUpdateRequest(revision=1)
        self.assertEqual(
            ContextFactCreateRequest(
                fact_type="preference", title="Editor", content="Vim"
            ).importance,
            50,
        )
        payload = McpContextFactSaveRequest(
            fact_type="preference",
            title="Editor",
            content="Vim",
            idempotency_key="retry-1",
        )
        self.assertEqual(payload.idempotency_key, "retry-1")


class ContextVaultServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_create_hashes_idempotency_and_schedules_after_transaction(self):
        repo = _repo()
        repo.create_fact.return_value = fact_row(
            revision=1,
            source_kind="mcp",
            source_ref="conversation:3",
            source_client_id="cursor",
            importance=80,
        )
        with patch("services.context_vault_service._repository", return_value=repo), patch(
            "services.context_vault_service.session_scope",
            return_value=_TransactionSession(),
        ), patch("services.context_vault_service.schedule_embedding") as schedule:
            result = await create_fact(
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

        self.assertEqual(result.id, 3)
        kwargs = repo.create_fact.call_args.kwargs
        self.assertEqual(
            kwargs["idempotency_key_hash"],
            sha256(b"7\0mcp\0cursor\0retry-1").hexdigest(),
        )
        schedule.assert_called_once_with(
            3, "preference", "Editor", "Uses vim keybindings", 1
        )

    async def test_idempotent_replay_does_not_schedule_embedding(self):
        repo = _repo()
        repo.create_fact.return_value = fact_row(_idempotent_replay=True)
        with patch("services.context_vault_service._repository", return_value=repo), patch(
            "services.context_vault_service.session_scope",
            return_value=_TransactionSession(),
        ), patch("services.context_vault_service.schedule_embedding") as schedule:
            result = await create_fact(
                7,
                fact_type="preference",
                title="Editor",
                content="Uses vim",
                idempotency_key="retry-1",
            )
        self.assertEqual(result.id, 3)
        schedule.assert_not_called()

    async def test_update_passes_revision_and_reembeds_active_fact(self):
        repo = _repo()
        repo.update_fact.return_value = fact_row(content="new", revision=3)
        with patch("services.context_vault_service._repository", return_value=repo), patch(
            "services.context_vault_service.session_scope",
            return_value=_TransactionSession(),
        ), patch("services.context_vault_service.schedule_embedding") as schedule:
            result = await update_fact(
                7,
                3,
                expected_revision=2,
                content="new",
                importance=90,
            )
        self.assertEqual(result.revision, 3)
        self.assertEqual(repo.update_fact.call_args.kwargs["expected_revision"], 2)
        schedule.assert_called_once()

    async def test_list_uses_keyset_cursor_and_total_active(self):
        repo = _repo()
        repo.list_facts.return_value = [fact_row(id=4), fact_row(id=3)]
        repo.count_active.return_value = 2
        with patch("services.context_vault_service._repository", return_value=repo):
            result = await list_facts(7, limit=1, session=object())
        self.assertEqual(len(result.facts), 1)
        self.assertEqual(result.total_active, 2)
        self.assertIsNotNone(result.next_cursor)
        repo.list_facts.assert_awaited_once()
        repo.count_active.assert_awaited_once_with(7)

    async def test_digest_groups_and_search_falls_back_from_semantic(self):
        repo = _repo()
        repo.list_active_for_digest.return_value = [
            fact_row(fact_type="project", importance=90),
            fact_row(id=4, fact_type="preference", importance=60),
        ]
        repo.semantic_search.return_value = []
        repo.text_search.return_value = [fact_row()]
        with patch("services.context_vault_service._repository", return_value=repo), patch(
            "services.context_vault_service.embeddings_available", return_value=True
        ), patch(
            "services.context_vault_service.asyncio.to_thread",
            new=AsyncMock(return_value=[0.1, 0.2]),
        ):
            digest = await build_digest(7, session=object())
            search = await search_facts(7, "editor", mode="semantic", session=object())
        self.assertEqual([group.fact_type for group in digest.groups], ["preference", "project"])
        self.assertEqual(len(search.facts), 1)
        repo.text_search.assert_awaited_once()

    async def test_search_rejects_empty_query(self):
        with self.assertRaises(ApiServiceError):
            await search_facts(7, " ", session=object())


if __name__ == "__main__":
    unittest.main()
