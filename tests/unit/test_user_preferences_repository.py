import unittest
from unittest.mock import patch

from services.repositories.user_preferences_repository import (
    get_user_preferred_locale,
    update_user_preferred_locale,
)


class FakeCursor:
    def __init__(self, row=None):
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
        self.cursor_value = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self, *args, **kwargs):
        return self.cursor_value

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class UserPreferencesRepositoryTestCase(unittest.TestCase):
    def test_get_returns_normalized_saved_locale(self):
        cursor = FakeCursor({"preferred_locale": "en"})
        with patch(
            "services.repositories.user_preferences_repository.get_db_connection",
            return_value=FakeConnection(cursor),
        ):
            self.assertEqual(get_user_preferred_locale(7), "en")
        self.assertEqual(cursor.executed[0][1], (7,))
        self.assertTrue(cursor.closed)

    def test_update_commits_existing_user(self):
        cursor = FakeCursor((7,))
        connection = FakeConnection(cursor)
        with patch(
            "services.repositories.user_preferences_repository.get_db_connection",
            return_value=connection,
        ):
            self.assertTrue(update_user_preferred_locale(7, "en"))
        self.assertEqual(cursor.executed[0][1], ("en", 7))
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)

    def test_update_rolls_back_missing_user(self):
        connection = FakeConnection(FakeCursor(None))
        with patch(
            "services.repositories.user_preferences_repository.get_db_connection",
            return_value=connection,
        ):
            self.assertFalse(update_user_preferred_locale(99, "ja"))
        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)


if __name__ == "__main__":
    unittest.main()
