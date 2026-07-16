import unittest
from unittest.mock import patch

from blueprints.memo.repository import update_memo
from services.api_errors import ApiServiceError


class FakeCursor:
    def __init__(self, existing, *, update_succeeds=True):
        self.existing = existing
        self.update_succeeds = update_succeeds
        self.executed = []
        self._result = None
        self.closed = False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))
        if normalized.startswith("SELECT me.title"):
            self._result = self.existing
        elif normalized.startswith("UPDATE memo_entries"):
            self._result = {"revision": int(self.existing["revision"]) + 1} if self.update_succeeds else None
        elif normalized.startswith("SELECT revision"):
            self._result = self.existing
        else:
            raise AssertionError(f"Unexpected query: {normalized}")

    def fetchone(self):
        return self._result

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit_calls = 0
        self.closed = False

    def cursor(self, *args, **kwargs):
        return self._cursor

    def commit(self):
        self.commit_calls += 1

    def close(self):
        self.closed = True


def existing_memo(**overrides):
    memo = {
        "title": "Before",
        "ai_response": "body",
        "collection_id": None,
        "background_color": None,
        "revision": 4,
        "is_shared": False,
    }
    memo.update(overrides)
    return memo


class MemoRevisionRepositoryTestCase(unittest.TestCase):
    def test_update_uses_revision_and_active_share_guards(self):
        cursor = FakeCursor(existing_memo())
        connection = FakeConnection(cursor)
        returned = {"id": 10, "title": "After", "ai_response": "body", "revision": 5}

        with (
            patch("blueprints.memo.repository._get_db_connection", return_value=connection),
            patch("blueprints.memo.repository.fetch_memo_detail", return_value=returned),
        ):
            result = update_memo(
                7,
                10,
                title="After",
                ai_response=None,
                collection_id=None,
                clear_collection=False,
                expected_revision=4,
                allow_shared_content_change=False,
            )

        update_sql, update_params = next(item for item in cursor.executed if item[0].startswith("UPDATE memo_entries"))
        self.assertIn("revision = revision + 1", update_sql)
        self.assertIn("AND revision = %s", update_sql)
        self.assertIn("AND NOT EXISTS", update_sql)
        self.assertEqual(update_params[-1], 4)
        self.assertEqual(result["revision"], 5)
        self.assertEqual(connection.commit_calls, 1)

    def test_update_rejects_stale_revision_before_write(self):
        cursor = FakeCursor(existing_memo(revision=5))
        connection = FakeConnection(cursor)
        with patch("blueprints.memo.repository._get_db_connection", return_value=connection):
            with self.assertRaises(ApiServiceError) as context:
                update_memo(
                    7,
                    10,
                    title="After",
                    ai_response=None,
                    collection_id=None,
                    clear_collection=False,
                    expected_revision=4,
                    allow_shared_content_change=False,
                )

        self.assertEqual(context.exception.status_code, 409)
        self.assertFalse(any(sql.startswith("UPDATE memo_entries") for sql, _ in cursor.executed))

    def test_update_rejects_active_shared_memo_without_acknowledgement(self):
        cursor = FakeCursor(existing_memo(is_shared=True))
        connection = FakeConnection(cursor)
        with patch("blueprints.memo.repository._get_db_connection", return_value=connection):
            with self.assertRaises(ApiServiceError) as context:
                update_memo(
                    7,
                    10,
                    title="After",
                    ai_response=None,
                    collection_id=None,
                    clear_collection=False,
                    expected_revision=4,
                    allow_shared_content_change=False,
                )

        self.assertEqual(context.exception.status_code, 409)
        self.assertIn("共有中", context.exception.message)

    def test_update_detects_revision_change_between_read_and_write(self):
        cursor = FakeCursor(existing_memo(), update_succeeds=False)
        connection = FakeConnection(cursor)
        with patch("blueprints.memo.repository._get_db_connection", return_value=connection):
            with self.assertRaises(ApiServiceError) as context:
                update_memo(
                    7,
                    10,
                    title="After",
                    ai_response=None,
                    collection_id=None,
                    clear_collection=False,
                    expected_revision=4,
                    allow_shared_content_change=True,
                )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(connection.commit_calls, 0)


if __name__ == "__main__":
    unittest.main()
