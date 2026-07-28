import unittest
from unittest.mock import patch

from blueprints.chat.tasks import _delete_task_for_user, _edit_task_for_user


class FakeCursor:
    def __init__(self, fetchone_result=(1,)):
        self.fetchone_result = fetchone_result
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

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
    def test_delete_english_system_name_uses_stable_key(self):
        connection = FakeConnection()
        with patch("blueprints.chat.tasks.get_db_connection", return_value=connection):
            _delete_task_for_user(7, "ℹ️ Explain a topic")

        query, params = connection.cursors[0].executed[0]
        self.assertIn("WHERE system_task_key = %s", query)
        self.assertEqual(params, ("information", 7))

    def test_editing_system_task_clears_provenance(self):
        connection = FakeConnection()
        with patch("blueprints.chat.tasks.get_db_connection", return_value=connection):
            updated = _edit_task_for_user(
                7,
                "ℹ️ Explain a topic",
                "My topic helper",
                "Custom prompt",
                "",
                "",
                "",
                "",
            )

        self.assertTrue(updated)
        update_query, update_params = connection.cursors[1].executed[0]
        self.assertIn("system_task_key = NULL", update_query)
        self.assertIn("WHERE system_task_key = %s", update_query)
        self.assertEqual(update_params[-2:], ("information", 7))


if __name__ == "__main__":
    unittest.main()
