import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from blueprints.prompt_share.prompt_share_api import (
    PROMPT_FEED_DEFAULT_LIMIT,
    PROMPT_FEED_MAX_LIMIT,
    _decode_prompt_feed_cursor,
    _encode_prompt_feed_cursor,
    _normalize_prompt_feed_filters,
    _parse_prompt_feed_limit,
    get_prompts,
)
from services.api_errors import ApiServiceError
from tests.helpers.request_helpers import build_request


class PromptFeedPaginationTestCase(unittest.TestCase):
    def test_cursor_round_trip_preserves_timestamp_and_id(self):
        cursor = _encode_prompt_feed_cursor(
            {"created_at": "2026-07-16T12:34:56", "id": 42}
        )

        self.assertIsInstance(cursor, str)
        self.assertEqual(
            _decode_prompt_feed_cursor(cursor),
            (datetime(2026, 7, 16, 12, 34, 56), 42),
        )

    def test_cursor_rejects_malformed_payloads(self):
        malformed_cursors = (
            "invalid",
            "e30",
            "eyJjcmVhdGVkX2F0Ijoibm90LWEtZGF0ZSIsImlkIjoxfQ",
        )
        for cursor in malformed_cursors:
            with self.subTest(cursor=cursor), self.assertRaises(ApiServiceError) as raised:
                _decode_prompt_feed_cursor(cursor)
            self.assertEqual(raised.exception.status_code, 400)

    def test_limit_defaults_and_clamps_to_supported_range(self):
        self.assertEqual(_parse_prompt_feed_limit(None), PROMPT_FEED_DEFAULT_LIMIT)
        self.assertEqual(_parse_prompt_feed_limit("invalid"), PROMPT_FEED_DEFAULT_LIMIT)
        self.assertEqual(_parse_prompt_feed_limit("0"), PROMPT_FEED_DEFAULT_LIMIT)
        self.assertEqual(_parse_prompt_feed_limit("999"), PROMPT_FEED_MAX_LIMIT)

    def test_filters_normalize_all_and_reject_unknown_values(self):
        self.assertEqual(
            _normalize_prompt_feed_filters("business", "prompt", "image"),
            ("business", "prompt", "image"),
        )
        self.assertEqual(
            _normalize_prompt_feed_filters("all", "all", None),
            (None, None, None),
        )
        with self.assertRaises(ApiServiceError):
            _normalize_prompt_feed_filters("unknown", "prompt", "text")

    def test_route_passes_cursor_and_filters_to_blocking_query(self):
        cursor = _encode_prompt_feed_cursor(
            {"created_at": "2026-07-16T12:34:56", "id": 42}
        )
        request = build_request(
            method="GET",
            path="/prompt_share/api/prompts",
            query_string=(
                f"limit=12&cursor={cursor}&category=business&"
                "content_format=prompt&media_type=text"
            ).encode("ascii"),
            session={"user_id": 7},
        )
        result = {
            "prompts": [{"id": 41}],
            "pagination": {"limit": 12, "has_next": False, "next_cursor": None},
        }

        with patch(
            "blueprints.prompt_share.prompt_share_api.run_blocking",
            new=AsyncMock(return_value=result),
        ) as run_blocking_mock:
            response = asyncio.run(get_prompts(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["prompts"], [{"id": 41}])
        self.assertEqual(payload["pagination"], result["pagination"])
        run_blocking_mock.assert_awaited_once_with(
            unittest.mock.ANY,
            7,
            limit=12,
            cursor=(datetime(2026, 7, 16, 12, 34, 56), 42),
            category="business",
            content_format="prompt",
            media_type="text",
        )

    def test_route_rejects_invalid_cursor_before_database_lookup(self):
        request = build_request(
            method="GET",
            path="/prompt_share/api/prompts",
            query_string=b"cursor=invalid",
        )

        with patch(
            "blueprints.prompt_share.prompt_share_api.run_blocking",
            new=AsyncMock(),
        ) as run_blocking_mock:
            response = asyncio.run(get_prompts(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "プロンプト一覧のカーソルが不正です。")
        run_blocking_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
