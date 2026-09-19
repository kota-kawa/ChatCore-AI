"""Regression tests for LIKE-pattern escaping in SharedContentRepository.

search_public_prompts used to interpolate the raw query into an ILIKE pattern
(``f"%{query}%"``), so a search term containing ``%`` or ``_`` matched far more
rows than the user typed (e.g. ``50%`` would match any row containing "50",
regardless of what followed).  list_public_content already routed through
``services.search_terms.build_like_pattern``; this file locks
search_public_prompts to the same behavior.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.repositories.shared_content_repository import SharedContentRepository
from services.search_terms import build_like_pattern


def _result(rows=None, scalar=0):
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows or []
    result.scalar_one.return_value = scalar
    return result


class SharedContentRepositorySearchTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_wildcard_characters_in_the_query_are_escaped(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result())
        repository = SharedContentRepository()

        await repository.search_public_prompts(
            session,
            query="50%_off",
            page=1,
            per_page=20,
            user_id=None,
            content_format=None,
            media_type=None,
            include_total=False,
            locale="ja",
            matching_category_keys=[],
        )

        params = session.execute.await_args.args[1]
        self.assertEqual(params["search_term"], build_like_pattern("50%_off"))
        # The raw query must not survive as an unescaped wildcard pattern.
        self.assertNotEqual(params["search_term"], "%50%_off%")
        self.assertIn("\\%", params["search_term"])
        self.assertIn("\\_", params["search_term"])

    async def test_count_query_reuses_the_same_escaped_term(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result(scalar=3))
        repository = SharedContentRepository()

        await repository.search_public_prompts(
            session,
            query="a_b",
            page=1,
            per_page=20,
            user_id=None,
            content_format=None,
            media_type=None,
            include_total=True,
            locale="ja",
            matching_category_keys=[],
        )

        self.assertEqual(session.execute.await_count, 2)
        for call in session.execute.await_args_list:
            self.assertEqual(call.args[1]["search_term"], build_like_pattern("a_b"))

    async def test_plain_query_without_wildcards_is_unaffected(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result())
        repository = SharedContentRepository()

        await repository.search_public_prompts(
            session,
            query="architecture",
            page=1,
            per_page=20,
            user_id=None,
            content_format=None,
            media_type=None,
            include_total=False,
            locale="ja",
            matching_category_keys=[],
        )

        params = session.execute.await_args.args[1]
        self.assertEqual(params["search_term"], "%architecture%")


if __name__ == "__main__":
    unittest.main()
