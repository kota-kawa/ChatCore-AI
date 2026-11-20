"""記憶の検索の取得（利用者単位の 1 回の読み取りと、検索語の埋め込みの扱い）を検証するテスト（ADR 0025）。

Tests memory-search retrieval: the single per-user read and how the query embedding is handled.
"""

import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects.postgresql import dialect

from services.context_vault_service import search_facts, search_facts_ranked
from services.repositories.context_fact_repository import ContextFactRepository


def _row(fact_id, title, content, **overrides):
    return {
        "id": fact_id,
        "fact_type": "preference",
        "title": title,
        "content": content,
        "importance": 50,
        "source_kind": "chat",
        "last_confirmed_at": None,
        "last_mentioned_at": datetime(2026, 11, 1, tzinfo=UTC),
        "distance": None,
        **overrides,
    }


class RepositoryQueryTestCase(unittest.IsolatedAsyncioTestCase):
    async def _sql(self, embedding):
        session = MagicMock()
        result = MagicMock()
        result.mappings.return_value.all.return_value = [{"id": 1}]
        session.execute = AsyncMock(return_value=result)
        rows = await ContextFactRepository(session).list_active_for_memory_search(7, embedding)
        self.assertEqual(rows, [{"id": 1}])
        self.assertEqual(session.execute.await_count, 1)
        return " ".join(str(session.execute.await_args.args[0].compile(dialect=dialect())).split())

    async def test_reads_only_the_users_active_facts_in_one_query(self):
        sql = await self._sql(None)

        self.assertIn("context_facts.user_id = %(user_id_1)s", sql)
        self.assertIn("context_facts.status = %(status_1)s", sql)
        self.assertEqual(sql.count("FROM context_facts"), 1)
        self.assertIn("LIMIT", sql)

    async def test_the_row_carries_what_the_ranking_and_the_result_need(self):
        sql = await self._sql(None)

        for column in ("importance", "source_kind", "last_confirmed_at", "fact_type", "title", "content"):
            self.assertIn(f"context_facts.{column}", sql)
        # 最後に話題に出た日は、毎ターンのまとめと同じ定義（出典の観測時刻の最大値、無ければ updated_at）。
        # Last mentioned uses the per-turn summary's definition (newest source observation, else updated_at).
        self.assertIn("max(context_fact_sources.observed_at)", sql)
        self.assertIn("AS last_mentioned_at", sql)

    async def test_the_distance_is_computed_in_the_same_query_only_with_an_embedding(self):
        with_embedding = await self._sql([0.1] * 768)
        without = await self._sql(None)

        self.assertIn("<=>", with_embedding)
        self.assertNotIn("<=>", without)
        self.assertIn("AS distance", without)
        # 意味の距離で行を絞らない（語の一致だけの行も順位づけの対象にするため）。
        # Rows are not filtered by distance: word-match-only rows still take part in ranking.
        self.assertNotIn("<=> %", with_embedding.split("FROM context_facts WHERE", 1)[1])


class SearchFactsRankedTestCase(unittest.IsolatedAsyncioTestCase):
    def _patch(self, rows, *, available=True, embedding=None, embed_error=None):
        repo = MagicMock()
        repo.list_active_for_memory_search = AsyncMock(return_value=rows)
        generate = MagicMock(return_value=embedding, side_effect=embed_error)
        return (
            repo,
            generate,
            patch("services.context_vault_service._repository", return_value=repo),
            patch("services.context_vault_service.embeddings_available", return_value=available),
            patch("services.context_vault_service.generate_embedding", generate),
        )

    async def test_reads_once_with_the_query_embedding_and_returns_the_ranked_facts(self):
        rows = [_row(1, "飼い犬", "柴犬のハチを飼っている。散歩は朝。", distance=0.2), _row(2, "勤務先", "株式会社サンプル", distance=0.9)]
        repo, generate, p1, p2, p3 = self._patch(rows, embedding=[0.1] * 768)
        with p1, p2, p3:
            ranked = await search_facts_ranked(7, " 犬の散歩 ", session=MagicMock())

        generate.assert_called_once_with("犬の散歩")
        repo.list_active_for_memory_search.assert_awaited_once_with(7, [0.1] * 768)
        self.assertEqual([fact["id"] for fact in ranked], [1])

    async def test_unavailable_embeddings_rank_by_word_match_and_skip_the_provider(self):
        rows = [_row(1, "飼い犬", "柴犬のハチを飼っている。散歩は朝。"), _row(2, "勤務先", "株式会社サンプル")]
        repo, generate, p1, p2, p3 = self._patch(rows, available=False)
        with p1, p2, p3:
            ranked = await search_facts_ranked(7, "犬の散歩", session=MagicMock())

        generate.assert_not_called()
        repo.list_active_for_memory_search.assert_awaited_once_with(7, None)
        self.assertEqual([fact["id"] for fact in ranked], [1])

    async def test_a_failed_embedding_does_not_fail_the_search_and_never_logs_the_query(self):
        rows = [_row(1, "飼い犬", "柴犬のハチを飼っている。散歩は朝。")]
        repo, _, p1, p2, p3 = self._patch(rows, embed_error=RuntimeError("SECRET-QUERY-9 leaked"))
        with p1, p2, p3, self.assertLogs("blueprints.context_vault", level="WARNING") as logs:
            ranked = await search_facts_ranked(7, "犬の散歩", session=MagicMock())

        repo.list_active_for_memory_search.assert_awaited_once_with(7, None)
        self.assertEqual([fact["id"] for fact in ranked], [1])
        self.assertNotIn("SECRET-QUERY-9", "\n".join(logs.output))
        self.assertTrue(all(record.exc_info is None for record in logs.records))

    async def test_a_blank_query_reads_nothing(self):
        repo, generate, p1, p2, p3 = self._patch([])
        with p1, p2, p3:
            self.assertEqual(await search_facts_ranked(7, "   ", session=MagicMock()), [])

        generate.assert_not_called()
        repo.list_active_for_memory_search.assert_not_awaited()

    async def test_the_existing_keyword_and_semantic_search_is_untouched(self):
        repo = MagicMock()
        repo.text_search = AsyncMock(return_value=[])
        repo.list_active_for_memory_search = AsyncMock()
        with patch("services.context_vault_service._repository", return_value=repo):
            await search_facts(7, "犬", mode="keyword", session=MagicMock())

        repo.text_search.assert_awaited_once()
        repo.list_active_for_memory_search.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
