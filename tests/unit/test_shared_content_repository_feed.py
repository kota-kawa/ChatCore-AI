"""SharedContentRepository の公開プロンプトフィードが生成する SQL の形を検証するテスト。

SQL-shape tests for the public prompt feed in SharedContentRepository.
"""

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from services.repositories.shared_content_repository import SharedContentRepository


# mappings().all() が行を返す DB 実行結果のモックを作る補助関数。
# Helper that builds a mocked DB result whose mappings().all() returns the rows.
def _result(rows=None):
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows or []
    return result


# 既定の引数で get_public_feed を呼ぶ補助関数。
# Helper that calls get_public_feed with default arguments.
async def _feed(session, **overrides):
    kwargs = {"user_id": None, "limit": 24, "locale": "ja"}
    kwargs.update(overrides)
    return await SharedContentRepository().get_public_feed(session, **kwargs)


# 公開フィードの SQL に、注目枠の先頭固定・同じフィルター条件・キーセット順序が含まれることを検証するテストクラス。
# Test class verifying that the feed SQL pins featured prompts first, applies the same filters, and keeps keyset ordering.
class SharedContentRepositoryFeedTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_first_page_leads_with_featured_prompts_and_exposes_counts(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result())

        await _feed(session)

        statement, params = session.execute.await_args.args
        sql = str(statement)
        self.assertIn("ORDER BY (p.featured_at IS NOT NULL) DESC, p.featured_at DESC, COALESCE(pvc.view_count, 0) DESC", sql)
        self.assertIn("ORDER BY (p.featured_at IS NOT NULL) DESC, p.featured_at DESC, p.view_count DESC", sql)
        self.assertNotIn("p.featured_at IS NULL", sql)
        self.assertIn("p.featured_at,", sql)
        self.assertIn("COALESCE(lc.like_count, 0) AS like_count", sql)
        self.assertIn("SELECT COUNT(*) AS like_count", sql)
        self.assertNotIn("feed_view_count", params)
        # 最初のページでは、通常のページに加えて注目の行をすべて取得する。
        # The first page fetches every featured row on top of the regular page.
        self.assertIn(":fetch_limit + (", sql)
        self.assertIn("SELECT COUNT(*) FROM prompts AS f", sql)
        self.assertIn("f.featured_at IS NOT NULL", sql)

    async def test_featured_count_on_the_first_page_honours_the_same_filters(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result())

        await _feed(session, category="business", content_format="skill", author_id=42)

        statement, params = session.execute.await_args.args
        sql = str(statement)
        self.assertIn("f.category = :feed_category", sql)
        self.assertIn("f.content_format = :feed_content_format", sql)
        self.assertIn("f.user_id = :feed_author_id", sql)
        self.assertEqual(params["feed_category"], "business")
        self.assertEqual(params["feed_author_id"], 42)

    async def test_later_pages_skip_featured_prompts_and_keep_the_keyset_order(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=_result())
        cursor = (12, datetime(2026, 7, 16, 10, 0, 0), 8)

        await _feed(session, cursor=cursor)

        statement, params = session.execute.await_args.args
        sql = str(statement)
        self.assertIn("p.featured_at IS NULL", sql)
        self.assertIn("< (:feed_view_count, :feed_created_at, :feed_id)", sql)
        self.assertNotIn("(p.featured_at IS NOT NULL) DESC", sql)
        self.assertIn("ORDER BY COALESCE(pvc.view_count, 0) DESC, p.created_at DESC, p.id DESC", sql)
        self.assertIn("LIMIT :fetch_limit\n", sql)
        self.assertNotIn("SELECT COUNT(*) FROM prompts AS f", sql)
        self.assertEqual((params["feed_view_count"], params["feed_created_at"], params["feed_id"]), cursor)


if __name__ == "__main__":
    unittest.main()
