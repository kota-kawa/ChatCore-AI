import unittest
from unittest.mock import patch

from blueprints.chat.tasks import _delete_task_for_user, _edit_task_for_user


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.fetchone_result = None
        self.rowcount = 0

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))
        if normalized.startswith("SELECT id FROM task_with_examples"):
            self.fetchone_result = (params[0],)
        elif normalized.startswith("SELECT 1 FROM task_with_examples"):
            self.fetchone_result = None
        else:
            self.fetchone_result = None
        if normalized.startswith("UPDATE task_with_examples"):
            self.rowcount = 1

    def fetchone(self):
        return self.fetchone_result

    def close(self):
        return None


class FakeConnection:
    def __init__(self):
        self.cursors = []
        self.committed = False

    def cursor(self, *args, **kwargs):
        cursor = FakeCursor()
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        self.committed = True

    def close(self):
        return None


class LocalizedTaskOperationsTestCase(unittest.TestCase):
    def test_delete_uses_owned_task_id(self):
        connection = FakeConnection()
        with patch("blueprints.chat.tasks.get_db_connection", return_value=connection):
            _delete_task_for_user(7, 42)

        query, params = connection.cursors[0].executed[1]
        self.assertIn("WHERE id = %s", query)
        self.assertEqual(params, (42, 7))

    def test_editing_system_task_preserves_provenance_and_marks_customized(self):
        connection = FakeConnection()
        with patch("blueprints.chat.tasks.get_db_connection", return_value=connection):
            updated = _edit_task_for_user(
                7,
                42,
                "My topic helper",
                "Custom prompt",
                "",
                "",
                "",
                "",
            )

        self.assertTrue(updated)
        update_query, update_params = connection.cursors[1].executed[0]
        self.assertNotIn("system_task_key = NULL", update_query)
        self.assertIn("is_system_task_customized", update_query)
        self.assertIn("WHERE id = %s", update_query)
        self.assertEqual(update_params[-2:], (42, 7))


if __name__ == "__main__":
    unittest.main()
