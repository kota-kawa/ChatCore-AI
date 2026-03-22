import unittest
from unittest.mock import patch

from blueprints.chat.tasks import _delete_task_for_user
from blueprints.prompt_share.prompt_manage_api import (
    _delete_prompt_for_user,
    _delete_saved_prompt_for_user,
)
from blueprints.prompt_share.prompt_share_api import _remove_bookmark_for_user


class FakeCursor:
    def __init__(self, *, rowcount=1):
        self.rowcount = rowcount
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.closed = False

    def cursor(self, *args, **kwargs):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class SoftDeleteQueryTestCase(unittest.TestCase):
    def test_delete_task_marks_row_deleted_instead_of_hard_deleting(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        with patch("blueprints.chat.tasks.get_db_connection", return_value=fake_conn):
            _delete_task_for_user(5, "Task A")

        query, params = fake_cursor.executed[0]
        self.assertIn("UPDATE task_with_examples SET deleted_at = CURRENT_TIMESTAMP", query)
        self.assertNotIn("DELETE FROM task_with_examples", query)
        self.assertEqual(params, ("Task A", 5))
        self.assertTrue(fake_conn.committed)

    def test_delete_saved_prompt_marks_task_row_deleted(self):
        fake_cursor = FakeCursor(rowcount=1)
        fake_conn = FakeConnection(fake_cursor)

        with patch("blueprints.prompt_share.prompt_manage_api.get_db_connection", return_value=fake_conn):
            deleted = _delete_saved_prompt_for_user(8, 99)

        query, params = fake_cursor.executed[0]
        self.assertEqual(deleted, 1)
        self.assertIn("UPDATE task_with_examples SET deleted_at = CURRENT_TIMESTAMP", query)
        self.assertEqual(params, (99, 8))

    def test_delete_prompt_marks_prompt_row_deleted(self):
        fake_cursor = FakeCursor(rowcount=1)
        fake_conn = FakeConnection(fake_cursor)

        with patch("blueprints.prompt_share.prompt_manage_api.get_db_connection", return_value=fake_conn):
            deleted = _delete_prompt_for_user(8, 77)

        query, params = fake_cursor.executed[0]
        self.assertEqual(deleted, 1)
        self.assertIn("UPDATE prompts SET deleted_at = CURRENT_TIMESTAMP", query)
        self.assertNotIn("DELETE FROM prompts", query)
        self.assertEqual(params, (77, 8))

    def test_remove_bookmark_marks_task_row_deleted(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        with patch("blueprints.prompt_share.prompt_share_api.get_db_connection", return_value=fake_conn):
            _remove_bookmark_for_user(3, "Bookmark Title")

        query, params = fake_cursor.executed[0]
        self.assertIn("UPDATE task_with_examples SET deleted_at = CURRENT_TIMESTAMP", query)
        self.assertEqual(params, (3, "Bookmark Title"))


if __name__ == "__main__":
    unittest.main()
