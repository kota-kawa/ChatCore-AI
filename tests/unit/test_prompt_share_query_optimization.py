import unittest
from datetime import datetime

from blueprints.prompt_share.prompt_share_api import (
    _decode_prompt_feed_cursor,
    _encode_prompt_feed_cursor,
    _get_prompts_with_flags,
    _get_recommended_prompts,
)


class _Service:
    def __init__(self, rows):
        self.rows = rows
        self.feed_calls = []
        self.recommendation_calls = []

    async def get_public_feed(self, **kwargs):
        self.feed_calls.append(kwargs)
        return self.rows

    async def get_recommended_prompts(self, **kwargs):
        self.recommendation_calls.append(kwargs)
        return self.rows


class PromptShareQueryOptimizationTestCase(unittest.IsolatedAsyncioTestCase):
    def _rows(self):
        return [
            {
                "id": 1,
                "title": "Prompt",
                "category": "business",
                "content": "Body",
                "author": "tester",
                "content_format": "prompt",
                "media_type": "text",
                "attributes": {},
                "attachments": [],
                "created_at": datetime(2026, 7, 16, 10, 0, 0),
                "view_count": 12,
                "liked": True,
                "used_in_chat": True,
                "comment_count": 2,
            }
        ]

    async def test_feed_delegates_cte_work_to_async_service_and_serializes_flags(self):
        from unittest.mock import patch

        service = _Service(self._rows())
        with patch("blueprints.prompt_share.prompt_share_api._service", return_value=service):
            payload = await _get_prompts_with_flags(7, limit=25, locale="ja")
        self.assertTrue(payload["prompts"][0]["liked"])
        self.assertTrue(payload["prompts"][0]["used_in_chat"])
        self.assertFalse(payload["pagination"]["has_next"])
        self.assertEqual(service.feed_calls[0]["user_id"], 7)

    async def test_feed_passes_cursor_and_filters_without_database_api_objects(self):
        from unittest.mock import patch

        service = _Service(self._rows())
        cursor = (12, datetime(2026, 7, 16, 11, 0, 0), 10)
        with patch("blueprints.prompt_share.prompt_share_api._service", return_value=service):
            await _get_prompts_with_flags(
                7,
                limit=2,
                cursor=cursor,
                category="business",
                content_format="prompt",
                media_type="image",
                author_id=42,
            )
        self.assertEqual(service.feed_calls[0]["cursor"], cursor)
        self.assertEqual(service.feed_calls[0]["author_id"], 42)

    async def test_recommendations_delegate_to_service(self):
        from unittest.mock import patch

        service = _Service(self._rows())
        with patch("blueprints.prompt_share.prompt_share_api._service", return_value=service):
            prompts = await _get_recommended_prompts(7, 3, "ja")
        self.assertEqual(prompts[0]["id"], 1)
        self.assertEqual(service.recommendation_calls[0]["exclude_prompt_id"], 7)

    def test_feed_cursor_round_trip(self):
        value = _encode_prompt_feed_cursor(
            {"id": 8, "view_count": 12, "created_at": "2026-07-16T10:00:00"}
        )
        self.assertEqual(
            _decode_prompt_feed_cursor(value),
            (12, datetime(2026, 7, 16, 10, 0, 0), 8),
        )


if __name__ == "__main__":
    unittest.main()
