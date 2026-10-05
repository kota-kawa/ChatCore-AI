import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects.postgresql import dialect

from services.repositories.memo_repository import fetch_memo_summaries


def _result(rows):
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


def _memo_row(*, title="Semantic result", preview="body"):
    return {
        "id": 1,
        "title": title,
        "created_at": None,
        "updated_at": None,
        "revision": 1,
        "archived_at": None,
        "pinned_at": None,
        "preview_response": preview,
        "collection_id": None,
        "background_color": None,
        "collection_name": None,
        "collection_color": None,
        "share_token": None,
        "expires_at": None,
        "revoked_at": None,
    }


class MemoSearchRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_semantic_search_uses_pgvector_and_database_pagination(self):
        session = MagicMock()
        session.scalar = AsyncMock(return_value=900)
        session.execute = AsyncMock(return_value=_result([_memo_row()]))

        result = await fetch_memo_summaries(
            7,
            limit=20,
            offset=400,
            query="architecture",
            date_from="",
            date_to="",
            sort="recent",
            include_archived=False,
            only_archived=False,
            pinned_first=True,
            collection_id=None,
            semantic_query_embedding=[0.1, 0.2, 0.3],
            session=session,
        )

        self.assertEqual(result["total"], 900)
        self.assertEqual(result["memos"][0]["id"], 1)
        statement = session.execute.await_args.args[0]
        compiled = str(statement.compile(dialect=dialect()))
        self.assertIn("embedding_vector <=>", compiled)
        self.assertIn("LIMIT", compiled)
        self.assertIn("OFFSET", compiled)

    async def test_semantic_search_applies_distance_threshold_to_count_and_rows(self):
        session = MagicMock()
        session.scalar = AsyncMock(return_value=1)
        session.execute = AsyncMock(return_value=_result([_memo_row()]))

        with patch(
            "services.repositories.memo_repository.get_semantic_max_distance",
            return_value=0.4,
        ):
            await fetch_memo_summaries(
                7,
                limit=5,
                offset=0,
                query="architecture",
                date_from="",
                date_to="",
                sort="recent",
                include_archived=False,
                only_archived=False,
                pinned_first=False,
                collection_id=None,
                semantic_query_embedding=[0.1, 0.2, 0.3],
                session=session,
            )

        count_statement = session.scalar.await_args.args[0]
        row_statement = session.execute.await_args.args[0]
        self.assertIn("embedding_vector <=>", str(count_statement.compile(dialect=dialect())))
        self.assertIn("embedding_vector <=>", str(row_statement.compile(dialect=dialect())))
        self.assertIn(0.4, count_statement.compile(dialect=dialect()).params.values())

    async def test_keyword_search_requires_every_term_and_escapes_wildcards(self):
        session = MagicMock()
        session.scalar = AsyncMock(return_value=0)
        session.execute = AsyncMock(return_value=_result([]))

        await fetch_memo_summaries(
            7,
            limit=10,
            offset=0,
            query="沖縄旅行 100%",
            date_from="",
            date_to="",
            sort="recent",
            include_archived=False,
            only_archived=False,
            pinned_first=False,
            collection_id=None,
            semantic_query_embedding=None,
            session=session,
        )

        statement = session.scalar.await_args.args[0]
        compiled = statement.compile(dialect=dialect())
        sql = str(compiled)
        self.assertGreaterEqual(sql.count("ILIKE"), 4)
        self.assertIn("ESCAPE", sql)
        self.assertIn("%100\\%%", compiled.params.values())

    async def test_keyword_search_matches_hiragana_and_katakana_spellings(self):
        session = MagicMock()
        session.scalar = AsyncMock(return_value=0)
        session.execute = AsyncMock(return_value=_result([]))

        await fetch_memo_summaries(
            7,
            limit=10,
            offset=0,
            query="ぱすぽーと",
            date_from="",
            date_to="",
            sort="recent",
            include_archived=False,
            only_archived=False,
            pinned_first=False,
            collection_id=None,
            semantic_query_embedding=None,
            session=session,
        )

        compiled = session.scalar.await_args.args[0].compile(dialect=dialect())
        # 両方の綴り × タイトル・本文。列には関数をかけず、pg_trgm の索引を使える形のまま。
        # Both spellings x title and body, with no function on the columns so pg_trgm indexes still apply.
        self.assertEqual(str(compiled).count("ILIKE"), 4)
        self.assertNotIn("lower(memo_entries", str(compiled))
        self.assertIn("%ぱすぽーと%", compiled.params.values())
        self.assertIn("%パスポート%", compiled.params.values())

    async def test_keyword_search_without_kana_keeps_one_condition_per_column(self):
        session = MagicMock()
        session.scalar = AsyncMock(return_value=0)
        session.execute = AsyncMock(return_value=_result([]))

        await fetch_memo_summaries(
            7,
            limit=10,
            offset=0,
            query="passport",
            date_from="",
            date_to="",
            sort="recent",
            include_archived=False,
            only_archived=False,
            pinned_first=False,
            collection_id=None,
            semantic_query_embedding=None,
            session=session,
        )

        self.assertEqual(str(session.scalar.await_args.args[0].compile(dialect=dialect())).count("ILIKE"), 2)


if __name__ == "__main__":
    unittest.main()
