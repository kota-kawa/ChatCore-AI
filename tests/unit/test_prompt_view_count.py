import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from blueprints.prompt_share.prompt_share_api import (
    _get_public_prompt_by_id,
    record_prompt_view,
)
from services.repositories.prompt_view_repository import PromptViewRepository


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self, *args, **kwargs):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self.close()
        return False


class PromptViewCountTestCase(unittest.TestCase):
    def test_prompt_detail_returns_current_view_count_without_incrementing_it(self):
        fake_cursor = FakeCursor(
            {
                "id": 42,
                "title": "Prompt",
                "content": "Body",
                "content_format": "prompt",
                "media_type": "text",
                "view_count": 5,
            }
        )
        fake_conn = FakeConnection(fake_cursor)

        with patch(
            "blueprints.prompt_share.prompt_share_api.get_db_connection",
            return_value=fake_conn,
        ):
            prompt = _get_public_prompt_by_id(42)

        self.assertEqual(prompt["view_count"], 5)
        query, params = fake_cursor.executed[0]
        self.assertIn("LEFT JOIN prompt_view_counts AS pvc", query)
        self.assertNotIn("UPDATE prompts", query)
        self.assertEqual(params, (42,))
        self.assertEqual(fake_conn.commits, 0)

    def test_record_view_atomically_upserts_for_an_active_public_prompt(self):
        fake_cursor = FakeCursor({"view_count": 6})
        fake_conn = FakeConnection(fake_cursor)

        with patch(
            "services.repositories.prompt_view_repository.get_db_connection",
            return_value=fake_conn,
        ):
            view_count = PromptViewRepository.increment_public_view(42)

        self.assertEqual(view_count, 6)
        self.assertEqual(fake_conn.commits, 1)
        query, params = fake_cursor.executed[0]
        self.assertIn("INSERT INTO prompt_view_counts AS pvc", query)
        self.assertIn("p.is_public = TRUE", query)
        self.assertIn("p.deleted_at IS NULL", query)
        self.assertIn("ON CONFLICT (prompt_id) DO UPDATE", query)
        self.assertIn("SET view_count = pvc.view_count + 1", query)
        self.assertEqual(params, (42,))
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_conn.closed)

    def test_record_view_does_not_commit_when_prompt_is_not_public_and_active(self):
        fake_cursor = FakeCursor(None)
        fake_conn = FakeConnection(fake_cursor)

        with patch(
            "services.repositories.prompt_view_repository.get_db_connection",
            return_value=fake_conn,
        ):
            view_count = PromptViewRepository.increment_public_view(99)

        self.assertIsNone(view_count)
        self.assertEqual(fake_conn.commits, 0)
        self.assertEqual(fake_conn.rollbacks, 1)

    def test_record_view_endpoint_returns_incremented_count(self):
        with patch(
            "blueprints.prompt_share.prompt_share_api.run_blocking",
            new=AsyncMock(return_value=8),
        ) as run_blocking_mock:
            response = asyncio.run(record_prompt_view(42))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body.decode("utf-8"))["view_count"], 8)
        run_blocking_mock.assert_awaited_once_with(
            PromptViewRepository.increment_public_view,
            42,
        )

    def test_record_view_endpoint_returns_404_for_unavailable_prompt(self):
        with patch(
            "blueprints.prompt_share.prompt_share_api.run_blocking",
            new=AsyncMock(return_value=None),
        ):
            response = asyncio.run(record_prompt_view(99))

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
