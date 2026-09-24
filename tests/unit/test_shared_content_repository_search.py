"""SQL-shape tests for search and recommendations in SharedContentRepository.

search_public_prompts used to interpolate the raw query into an ILIKE pattern
(``f"%{query}%"``), so a search term containing ``%`` or ``_`` matched far more
rows than the user typed (e.g. ``50%`` would match any row containing "50",
regardless of what followed).  list_public_content already routed through
``services.search_terms.build_like_pattern``; this file locks
search_public_prompts to the same behavior, and to the word-first, meaning-second
ranking that the vector column added.
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


async def _search(session, **overrides):
    kwargs = {
        "query": "architecture",
        "page": 1,
        "per_page": 20,
        "user_id": None,
        "content_format": None,
        "media_type": None,
        "include_total": False,
        "locale": "ja",
        "matching_category_keys": [],
    }
    kwargs.update(overrides)
    return await SharedContentRepository().search_public_prompts(session, **kwargs)


class SharedContentRepositorySearchTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_wildcard_characters_in_the_query_are_escaped(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result())

        await _search(session, query="50%_off")

        params = session.execute.await_args.args[1]
        self.assertEqual(params["search_term_0"], build_like_pattern("50%_off"))
        # The raw query must not survive as an unescaped wildcard pattern.
        self.assertNotEqual(params["search_term_0"], "%50%_off%")
        self.assertIn("\\%", params["search_term_0"])
        self.assertIn("\\_", params["search_term_0"])

    async def test_count_query_reuses_the_same_escaped_term(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result(scalar=3))

        await _search(session, query="a_b", include_total=True)

        self.assertEqual(session.execute.await_count, 2)
        for call in session.execute.await_args_list:
            self.assertEqual(call.args[1]["search_term_0"], build_like_pattern("a_b"))

    async def test_plain_query_without_wildcards_is_unaffected(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result())

        await _search(session, query="architecture")

        params = session.execute.await_args.args[1]
        self.assertEqual(params["search_term_0"], "%architecture%")

    async def test_every_term_must_hit_and_title_hits_rank_first(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result())

        await _search(session, query="議事録 要約")

        statement, params = session.execute.await_args.args
        sql = str(statement)
        self.assertEqual(params["search_term_0"], "%議事録%")
        self.assertEqual(params["search_term_1"], "%要約%")
        self.assertIn("p.title ILIKE :search_term_0 ESCAPE '\\'", sql)
        self.assertIn("p.title ILIKE :search_term_1 ESCAPE '\\'", sql)
        # Both term groups are required, and the rank counts title hits highest.
        self.assertIn(") AND (", sql)
        self.assertIn("THEN 3 WHEN", sql)
        self.assertIn("ORDER BY p.lexical_rank DESC, p.semantic_distance ASC NULLS LAST", sql)

    async def test_lexical_only_search_binds_no_vector(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result())

        await _search(session, query="architecture")

        statement, params = session.execute.await_args.args
        self.assertNotIn("query_embedding", params)
        self.assertNotIn("<=>", str(statement))
        self.assertIn("NULL::double precision AS semantic_distance", str(statement))

    async def test_query_vector_widens_the_match_and_binds_the_ceiling(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result())

        await _search(session, query="architecture", query_embedding=[0.1, 0.2])

        statement, params = session.execute.await_args.args
        sql = str(statement)
        self.assertEqual(params["query_embedding"], [0.1, 0.2])
        self.assertGreater(params["semantic_max_distance"], 0)
        self.assertIn("p.embedding_vector <=> :query_embedding", sql)
        self.assertIn("<= :semantic_max_distance", sql)
        self.assertIn("OR (p.embedding_vector IS NOT NULL", sql)


class SharedContentRepositoryRecommendationTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_recommendations_rank_by_anchor_distance_then_category_then_views(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result())

        await SharedContentRepository().get_recommended_prompts(
            session,
            exclude_prompt_id=12,
            limit=3,
            locale="ja",
        )

        statement, params = session.execute.await_args.args
        sql = str(statement)
        self.assertEqual(params["exclude_prompt_id"], 12)
        self.assertEqual(params["limit"], 3)
        self.assertGreater(params["semantic_max_distance"], 0)
        self.assertIn("WITH anchor AS", sql)
        self.assertIn("p.embedding_vector <=> anchor.embedding_vector", sql)
        self.assertIn(
            "ORDER BY semantic_distance ASC NULLS LAST, same_category DESC,\n                  view_count DESC, RANDOM()",
            sql,
        )
        self.assertIn("COALESCE(p.id <> :exclude_prompt_id, TRUE)", sql)


if __name__ == "__main__":
    unittest.main()
