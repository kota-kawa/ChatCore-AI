import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from services.api_errors import ApiServiceError
from services.mcp_memo_service import (
    append_memo,
    create_memo,
    get_memo,
    list_collections,
    list_memos,
    search_memos,
    update_memo,
)
from services.request_models import (
    McpMemoAppendRequest,
    McpMemoCreateRequest,
    McpMemoUpdateRequest,
)


def memo_payload(**overrides):
    payload = {
        "id": 10,
        "title": "Private memo",
        "ai_response": "secret body",
        "created_at": "2026-07-16T01:00:00",
        "updated_at": "2026-07-16T02:00:00",
        "revision": 4,
        "is_archived": False,
        "is_pinned": False,
        "collection_id": None,
        "collection_name": None,
        "is_active": True,
        "share_token": "must-not-leak",
        "share_url": "https://example.test/shared/memo/must-not-leak",
        "excerpt": "secret excerpt",
    }
    payload.update(overrides)
    return payload


class _SessionScope:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def begin(self):
        return self


class McpMemoRequestModelTestCase(unittest.TestCase):
    def test_update_requires_revision_and_changed_field(self):
        with self.assertRaises(ValidationError):
            McpMemoUpdateRequest(expected_revision=1)
        with self.assertRaises(ValidationError):
            McpMemoUpdateRequest(expected_revision=0, title="title")


class McpMemoServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_list_returns_allowlisted_metadata_without_share_bearer(self):
        fetch = AsyncMock(return_value={"total": 1, "memos": [memo_payload()]})
        with patch("services.mcp_memo_service.fetch_memo_summaries", new=fetch):
            result = await list_memos(7, limit=500, offset=-10)
        serialized = result.model_dump()
        self.assertEqual(serialized["memos"][0]["revision"], 4)
        self.assertTrue(serialized["memos"][0]["is_shared"])
        self.assertNotIn("share_token", serialized["memos"][0])
        self.assertEqual(fetch.await_args.kwargs["limit"], 100)
        self.assertEqual(fetch.await_args.kwargs["offset"], 0)

    async def test_search_uses_async_embedding_thread_and_returns_excerpt(self):
        fetch = AsyncMock(return_value={"total": 1, "memos": [memo_payload()]})
        with patch("services.mcp_memo_service.embeddings_available", return_value=True), patch(
            "services.mcp_memo_service.generate_embedding", return_value=[0.1, 0.2]
        ), patch("services.mcp_memo_service.fetch_memo_summaries", new=fetch):
            result = await search_memos(7, " architecture ", mode="semantic")
        self.assertEqual(result.memos[0].excerpt, "secret excerpt")
        self.assertEqual(fetch.await_args.kwargs["query"], "architecture")
        self.assertEqual(fetch.await_args.kwargs["semantic_query_embedding"], [0.1, 0.2])

    async def test_search_requires_non_empty_query(self):
        with self.assertRaises(ApiServiceError) as error:
            await search_memos(7, "  ")
        self.assertEqual(error.exception.status_code, 400)

    async def test_semantic_search_falls_back_to_keyword_when_embedding_fails(self):
        fetch = AsyncMock(return_value={"total": 0, "memos": []})
        with patch("services.mcp_memo_service.embeddings_available", return_value=True), patch(
            "services.mcp_memo_service.generate_embedding",
            side_effect=RuntimeError("offline"),
        ), patch("services.mcp_memo_service.fetch_memo_summaries", new=fetch):
            result = await search_memos(7, "architecture", mode="semantic")
        self.assertEqual(result.total, 0)
        self.assertIsNone(fetch.await_args.kwargs["semantic_query_embedding"])

    async def test_get_maps_ai_response_to_content_without_share_token(self):
        fetch = AsyncMock(return_value=memo_payload())
        with patch("services.mcp_memo_service.fetch_memo_detail", new=fetch):
            result = await get_memo(7, 10)
        self.assertEqual(result.content, "secret body")
        self.assertNotIn("share_token", result.model_dump())
        fetch.assert_awaited_once_with(7, 10, session=None)

    async def test_update_passes_revision_and_schedules_embedding(self):
        updated = memo_payload(title="Updated", ai_response="new body", revision=5)
        payload = McpMemoUpdateRequest(expected_revision=4, title="Updated", content="new body")
        repository_update = AsyncMock(return_value=updated)
        with patch(
            "services.mcp_memo_service.update_memo_record",
            new=repository_update,
        ), patch("services.mcp_memo_service.schedule_embedding") as schedule:
            result = await update_memo(7, 10, payload)
        self.assertEqual(result.revision, 5)
        self.assertEqual(repository_update.await_args.kwargs["expected_revision"], 4)
        schedule.assert_called_once_with(10, "Updated", "new body", 5)

    async def test_create_and_append_keep_write_transactions_and_revision_guard(self):
        created = memo_payload(
            id=42,
            title="created body",
            ai_response="created body",
            revision=1,
        )
        insert = AsyncMock(return_value=42)
        detail = AsyncMock(return_value=created)
        with patch("services.mcp_memo_service.session_scope", return_value=_SessionScope()), patch(
            "services.mcp_memo_service.insert_memo", new=insert
        ), patch("services.mcp_memo_service.fetch_memo_detail", new=detail), patch(
            "services.mcp_memo_service.schedule_embedding"
        ) as schedule:
            result = await create_memo(7, McpMemoCreateRequest(title="", content="created body"))
        self.assertEqual(result.content, "created body")
        self.assertEqual(insert.await_args.args[:4], (7, "created body", "created body", None))
        schedule.assert_called_once_with(42, "created body", "created body", 1)

        current = memo_payload(ai_response="first", revision=4, is_active=False)
        updated = memo_payload(ai_response="first\n\nsecond", revision=5, is_active=False)
        detail.reset_mock()
        detail.return_value = current
        repository_update = AsyncMock(return_value=updated)
        payload = McpMemoAppendRequest(expected_revision=4, text="second")
        with patch("services.mcp_memo_service.session_scope", return_value=_SessionScope()), patch(
            "services.mcp_memo_service.fetch_memo_detail", new=detail
        ), patch("services.mcp_memo_service.update_memo_record", new=repository_update), patch(
            "services.mcp_memo_service.schedule_embedding"
        ):
            result = await append_memo(7, 10, payload)
        self.assertEqual(result.content, "first\n\nsecond")
        self.assertEqual(repository_update.await_args.kwargs["expected_revision"], 4)
        self.assertEqual(repository_update.await_args.kwargs["ai_response"], "first\n\nsecond")

    async def test_list_collections_returns_owner_scoped_dto(self):
        fetch = AsyncMock(return_value=[{"id": 2, "name": "Work", "color": "#123456", "memo_count": 3}])
        with patch("services.mcp_memo_service.fetch_collections", new=fetch):
            result = await list_collections(7)
        self.assertEqual(result.collections[0].name, "Work")
        fetch.assert_awaited_once_with(7, session=None)


if __name__ == "__main__":
    unittest.main()
