"""記憶の画面の一覧の検索語(ContextFactRepository.list_facts の query)の SQL を検証するテスト。
語の分け方と LIKE のエスケープが既存のキーワード検索と同じで、種類・状態・ページ送りと組み合わさることを確かめる。

Tests the SQL of the memory screen's list search (the query of ContextFactRepository.list_facts): terms are split and LIKE-escaped
as in the existing keyword search, and combine with type, status and paging.
"""

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects.postgresql import dialect

from services.repositories.context_fact_repository import ContextFactRepository
from tests.helpers.sql_helpers import bind_statement_parameters


async def _list(**kwargs):
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    await ContextFactRepository(session).list_facts(7, **kwargs)
    statement = session.execute.await_args.args[0]
    return " ".join(str(statement.compile(dialect=dialect())).split()), bind_statement_parameters(statement)


class ContextFactListSearchTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_without_a_query_there_is_no_text_condition(self):
        sql, _ = await _list()
        self.assertNotIn("ILIKE", sql)
        self.assertIn("context_facts.user_id =", sql)

    async def test_blank_or_separator_only_query_adds_no_condition(self):
        for query in ("", "   ", "、。 ,"):
            with self.subTest(query=query):
                sql, _ = await _list(query=query)
                self.assertNotIn("ILIKE", sql)

    async def test_each_term_must_match_title_or_content_case_insensitively(self):
        sql, bound = await _list(query="Tokyo 住所")
        self.assertEqual(sql.count("ILIKE"), 4)
        self.assertEqual(sql.count("context_facts.title ILIKE"), 2)
        self.assertEqual(sql.count("context_facts.content ILIKE"), 2)
        self.assertIn("ESCAPE", sql)
        self.assertIn("%Tokyo%", bound.values())
        self.assertIn("%住所%", bound.values())
        # 語ごとに (title OR content)、語どうしは AND（どちらの語も含む行だけ）。
        # Each term is (title OR content) and the terms are ANDed: only rows containing both.
        self.assertEqual(sql.count(") AND (context_facts.title ILIKE"), 1)
        self.assertEqual(sql.count(" OR context_facts.content ILIKE"), 2)

    async def test_like_wildcards_in_the_query_are_escaped(self):
        _, bound = await _list(query="100%_\\")
        self.assertIn("%100\\%\\_\\\\%", bound.values())

    async def test_query_combines_with_type_status_and_the_keyset_cursor(self):
        sql, bound = await _list(
            fact_type="profile",
            status="deprecated",
            query="東京",
            limit=21,
            before_updated_at=datetime(2026, 11, 1, 3, 0),
            before_id=40,
        )
        for part in (
            "context_facts.user_id =",
            "context_facts.status =",
            "context_facts.fact_type =",
            "ILIKE",
            "(context_facts.updated_at, context_facts.id) <",
        ):
            self.assertIn(part, sql)
        self.assertIn("ORDER BY context_facts.updated_at DESC, context_facts.id DESC", sql)
        self.assertIn("deprecated", bound.values())
        self.assertIn("profile", bound.values())
        self.assertIn("%東京%", bound.values())
        self.assertIn(21, bound.values())

    async def test_the_number_of_terms_is_capped_like_the_existing_keyword_search(self):
        sql, _ = await _list(query=" ".join(f"w{index}" for index in range(20)))
        self.assertEqual(sql.count("context_facts.title ILIKE"), 8)


if __name__ == "__main__":
    unittest.main()
