"""記憶の一覧ルート(GET /api/context-facts)の検索語 q の扱い(前後の空白の除去、空なら検索しない、長すぎる語の拒否、
ほかの絞り込みとの受け渡し)を検証するテスト。

Tests how the memory list route (GET /api/context-facts) handles the search query q: trimming, treating a blank as no search,
rejecting an overlong query, and passing it along with the other filters.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from blueprints.context_vault.constants import MAX_CONTEXT_SEARCH_QUERY_LENGTH
from blueprints.context_vault.routes import api_list_context_facts
from services.response_models import ContextFactListResponse
from tests.helpers.request_helpers import build_request


class ListSearchRouteTestCase(unittest.TestCase):
    def _list(self, **kwargs):
        request = build_request(method="GET", path="/api/context-facts", session={"user_id": 7})
        service = AsyncMock(return_value=ContextFactListResponse(facts=[], total_active=0, next_cursor=None))
        with patch("blueprints.context_vault.routes.list_facts", new=service):
            response = asyncio.run(api_list_context_facts(request, **kwargs))
        return response, service

    def test_search_query_is_trimmed_and_passed_with_the_other_filters(self):
        response, service = self._list(q="  東京 住所 ", fact_type="profile", status="deprecated", cursor="c")
        self.assertEqual(response.status_code, 200)
        service.assert_awaited_once()
        kwargs = service.await_args.kwargs
        self.assertEqual(
            (kwargs["query"], kwargs["fact_type"], kwargs["status"], kwargs["cursor"]),
            ("東京 住所", "profile", "deprecated", "c"),
        )

    def test_blank_query_means_no_search(self):
        _, service = self._list(q="   ")
        self.assertIsNone(service.await_args.kwargs["query"])

    def test_too_long_query_is_400_without_reaching_the_service(self):
        response, service = self._list(q="a" * (MAX_CONTEXT_SEARCH_QUERY_LENGTH + 1))
        self.assertEqual(response.status_code, 400)
        service.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
