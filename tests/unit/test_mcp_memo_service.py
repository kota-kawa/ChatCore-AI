import unittest
from unittest.mock import patch

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


class McpMemoRequestModelTestCase(unittest.TestCase):
    def test_update_requires_revision_and_changed_field(self):
        with self.assertRaises(ValidationError):
            McpMemoUpdateRequest(expected_revision=1)
        with self.assertRaises(ValidationError):
            McpMemoUpdateRequest(expected_revision=0, title="title")

    def test_update_rejects_oversized_or_blank_content(self):
        with self.assertRaises(ValidationError):
            McpMemoUpdateRequest(expected_revision=1, content=" ")
        with self.assertRaises(ValidationError):
            McpMemoUpdateRequest(expected_revision=1, content="x" * 60001)
        with self.assertRaises(ValidationError):
            McpMemoUpdateRequest(expected_revision=1, title="x" * 256)


class McpMemoServiceTestCase(unittest.TestCase):
    def test_list_returns_allowlisted_metadata_without_share_bearer(self):
        with patch(
            "services.mcp_memo_service.fetch_memo_summaries",
            return_value={"total": 1, "memos": [memo_payload()]},
        ) as fetch:
            result = list_memos(7, limit=500, offset=-10)

        serialized = result.model_dump()
        self.assertEqual(serialized["memos"][0]["revision"], 4)
        self.assertTrue(serialized["memos"][0]["is_shared"])
        self.assertNotIn("share_token", serialized["memos"][0])
        self.assertNotIn("share_url", serialized["memos"][0])
        self.assertNotIn("content", serialized["memos"][0])
        self.assertEqual(fetch.call_args.args[0], 7)
        self.assertEqual(fetch.call_args.kwargs["limit"], 100)
        self.assertEqual(fetch.call_args.kwargs["offset"], 0)

    def test_search_returns_excerpt_and_uses_semantic_embedding(self):
        with (
            patch("services.mcp_memo_service.embeddings_available", return_value=True),
            patch("services.mcp_memo_service.generate_embedding", return_value=[0.1, 0.2]),
            patch(
                "services.mcp_memo_service.fetch_memo_summaries",
                return_value={"total": 1, "memos": [memo_payload()]},
            ) as fetch,
        ):
            result = search_memos(7, " architecture ", mode="semantic")

        self.assertEqual(result.memos[0].excerpt, "secret excerpt")
        self.assertEqual(fetch.call_args.kwargs["query"], "architecture")
        self.assertEqual(fetch.call_args.kwargs["semantic_query_embedding"], [0.1, 0.2])

    def test_search_requires_non_empty_query(self):
        with self.assertRaises(ApiServiceError) as context:
            search_memos(7, "  ")
        self.assertEqual(context.exception.status_code, 400)

    def test_semantic_search_falls_back_to_keyword_when_embedding_fails(self):
        with (
            patch("services.mcp_memo_service.embeddings_available", return_value=True),
            patch("services.mcp_memo_service.generate_embedding", side_effect=RuntimeError("offline")),
            patch("services.mcp_memo_service.logger.warning"),
            patch(
                "services.mcp_memo_service.fetch_memo_summaries",
                return_value={"total": 0, "memos": []},
            ) as fetch,
        ):
            result = search_memos(7, "architecture", mode="semantic")

        self.assertEqual(result.total, 0)
        self.assertIsNone(fetch.call_args.kwargs["semantic_query_embedding"])

    def test_get_maps_ai_response_to_content_without_share_token(self):
        with patch("services.mcp_memo_service.fetch_memo_detail", return_value=memo_payload()) as fetch:
            result = get_memo(7, 10)

        self.assertEqual(result.content, "secret body")
        self.assertNotIn("share_token", result.model_dump())
        fetch.assert_called_once_with(7, 10)

    def test_update_passes_revision_and_schedules_embedding(self):
        updated = memo_payload(title="Updated", ai_response="new body", revision=5)
        payload = McpMemoUpdateRequest(expected_revision=4, title="Updated", content="new body")
        with (
            patch("services.mcp_memo_service.update_memo_record", return_value=updated) as repository_update,
            patch("services.mcp_memo_service.schedule_embedding") as schedule,
        ):
            result = update_memo(7, 10, payload)

        self.assertEqual(result.revision, 5)
        self.assertEqual(repository_update.call_args.kwargs["expected_revision"], 4)
        self.assertFalse(repository_update.call_args.kwargs["allow_shared_content_change"])
        schedule.assert_called_once_with(10, "Updated", "new body", 5)

    def test_create_schedules_embedding_and_returns_detail(self):
        payload = McpMemoCreateRequest(title="", content="created body")
        created = memo_payload(title="created body", ai_response="created body", revision=1)
        with (
            patch("services.mcp_memo_service.insert_memo", return_value=42) as insert,
            patch("services.mcp_memo_service.fetch_memo_detail", return_value=created),
            patch("services.mcp_memo_service.schedule_embedding") as schedule,
        ):
            result = create_memo(7, payload)

        self.assertEqual(result.content, "created body")
        self.assertEqual(insert.call_args.args[:4], (7, "created body", "created body", None))
        schedule.assert_called_once_with(42, "created body", "created body", 1)

    def test_append_preserves_revision_guard_and_enforces_combined_limit(self):
        current = memo_payload(ai_response="first", revision=4, is_active=False)
        updated = memo_payload(ai_response="first\n\nsecond", revision=5, is_active=False)
        payload = McpMemoAppendRequest(expected_revision=4, text="second")
        with (
            patch("services.mcp_memo_service.fetch_memo_detail", return_value=current),
            patch("services.mcp_memo_service.update_memo_record", return_value=updated) as repository_update,
            patch("services.mcp_memo_service.schedule_embedding"),
        ):
            result = append_memo(7, 10, payload)

        self.assertEqual(result.content, "first\n\nsecond")
        self.assertEqual(repository_update.call_args.kwargs["expected_revision"], 4)
        self.assertEqual(repository_update.call_args.kwargs["ai_response"], "first\n\nsecond")

        too_large = memo_payload(ai_response="x" * 60000)
        with patch("services.mcp_memo_service.fetch_memo_detail", return_value=too_large):
            with self.assertRaises(ApiServiceError):
                append_memo(7, 10, payload)

    def test_list_collections_returns_owner_scoped_dto(self):
        with patch(
            "services.mcp_memo_service.fetch_collections",
            return_value=[{"id": 2, "name": "Work", "color": "#123456", "memo_count": 3}],
        ) as fetch:
            result = list_collections(7)

        self.assertEqual(result.collections[0].name, "Work")
        fetch.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
