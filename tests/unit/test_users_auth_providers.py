import unittest
from unittest.mock import patch

from services.users import (
    EMAIL_AUTH_PROVIDER,
    GOOGLE_AUTH_PROVIDER,
    create_user,
    get_user_by_email,
    get_user_by_google_id,
    link_google_account,
)


class FakeCursor:
    def __init__(self, *, fetchone_result=None):
        self.fetchone_result = fetchone_result
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))

    def fetchone(self):
        result = self.fetchone_result
        self.fetchone_result = None
        return result

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, *args, **kwargs):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class UserAuthProvidersTestCase(unittest.TestCase):
    def test_create_user_persists_email_provider_in_separate_table(self):
        fake_cursor = FakeCursor(fetchone_result=(321,))
        fake_conn = FakeConnection(fake_cursor)

        with patch("services.users.get_db_connection", return_value=fake_conn):
            user_id = create_user("user@example.com")

        self.assertEqual(user_id, 321)
        self.assertTrue(fake_conn.committed)
        self.assertFalse(fake_conn.rolled_back)
        self.assertTrue(fake_conn.closed)
        self.assertTrue(fake_cursor.closed)
        self.assertIn("INSERT INTO users ( email, username, avatar_url, is_verified ) VALUES (%s, %s, %s, %s) RETURNING id", fake_cursor.executed[0][0])
        self.assertIn("INSERT INTO user_auth_providers", fake_cursor.executed[1][0])
        self.assertEqual(
            fake_cursor.executed[1][1],
            (321, EMAIL_AUTH_PROVIDER, "user@example.com", "user@example.com"),
        )

    def test_link_google_account_upserts_google_provider_row(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        with patch("services.users.get_db_connection", return_value=fake_conn):
            link_google_account(7, "google-user-123", "user@example.com")

        self.assertTrue(fake_conn.committed)
        self.assertIn("INSERT INTO user_auth_providers", fake_cursor.executed[0][0])
        self.assertEqual(
            fake_cursor.executed[0][1],
            (7, GOOGLE_AUTH_PROVIDER, "google-user-123", "user@example.com"),
        )

    def test_get_user_by_google_id_joins_auth_provider_table(self):
        expected = {"id": 9, "email": "user@example.com", "provider_user_id": "google-user-123"}
        fake_cursor = FakeCursor(fetchone_result=expected)
        fake_conn = FakeConnection(fake_cursor)

        with patch("services.users.get_db_connection", return_value=fake_conn):
            user = get_user_by_google_id("google-user-123")

        self.assertEqual(user, expected)
        self.assertIn("FROM user_auth_providers AS p JOIN users AS u ON u.id = p.user_id", fake_cursor.executed[0][0])
        self.assertEqual(fake_cursor.executed[0][1], (GOOGLE_AUTH_PROVIDER, "google-user-123"))

    def test_get_user_by_email_keeps_google_provider_metadata_available(self):
        expected = {"id": 10, "email": "user@example.com", "provider_user_id": "google-user-999"}
        fake_cursor = FakeCursor(fetchone_result=expected)
        fake_conn = FakeConnection(fake_cursor)

        with patch("services.users.get_db_connection", return_value=fake_conn):
            user = get_user_by_email("user@example.com")

        self.assertEqual(user, expected)
        self.assertIn("LEFT JOIN user_auth_providers AS gap", fake_cursor.executed[0][0])
        self.assertEqual(fake_cursor.executed[0][1], (GOOGLE_AUTH_PROVIDER, "user@example.com"))


if __name__ == "__main__":
    unittest.main()
