import unittest
from unittest.mock import patch

from services.users import copy_default_tasks_for_user


DEFAULT_ROW = (
    "information",
    "Information",
    "Explain the topic",
    "",
    "",
    "",
    "",
    0,
)


class FakeCursor:
    def __init__(self, *, existing=False):
        self.existing = existing
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

    def fetchall(self):
        return [DEFAULT_ROW]

    def fetchone(self):
        return (1,) if self.existing else None

    def close(self):
        return None


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.committed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


class DefaultTaskCopyTestCase(unittest.TestCase):
    def test_deleted_or_legacy_named_task_suppresses_recopy(self):
        cursor = FakeCursor(existing=True)
        connection = FakeConnection(cursor)

        with patch("services.users.get_db_connection", return_value=connection):
            copy_default_tasks_for_user(7)

        existence_query = next(
            query
            for query, _ in cursor.executed
            if "SELECT 1 FROM task_with_examples" in query
        )
        self.assertIn("system_task_key = %s", existence_query)
        self.assertIn("LOWER(BTRIM(name))", existence_query)
        self.assertNotIn("deleted_at IS NULL", existence_query)
        self.assertFalse(any("INSERT INTO task_with_examples" in query for query, _ in cursor.executed))

    def test_copy_locks_user_and_uses_conflict_safe_insert(self):
        cursor = FakeCursor(existing=False)
        connection = FakeConnection(cursor)

        with patch("services.users.get_db_connection", return_value=connection):
            copy_default_tasks_for_user(7)

        queries = [query for query, _ in cursor.executed]
        self.assertTrue(any("SELECT pg_advisory_xact_lock(%s)" in q for q in queries))
        insert_query = next(q for q in queries if "INSERT INTO task_with_examples" in q)
        self.assertIn("ON CONFLICT DO NOTHING", insert_query)
        self.assertTrue(connection.committed)


if __name__ == "__main__":
    unittest.main()
