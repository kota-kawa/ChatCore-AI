"""SQL-shape tests for the public prompt feed in SharedContentRepository."""

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from services.repositories.shared_content_repository import SharedContentRepository


def _result(rows=None):
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows or []
    return result


async def _feed(session, **overrides):
    kwargs = {"user_id": None, "limit": 24, "locale": "ja"}
    kwargs.update(overrides)
    return await SharedContentRepository().get_public_feed(session, **kwargs)


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
        self.assertEqual((params["feed_view_count"], params["feed_created_at"], params["feed_id"]), cursor)


if __name__ == "__main__":
    unittest.main()
