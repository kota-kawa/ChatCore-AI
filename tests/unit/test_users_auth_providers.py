import unittest
from unittest.mock import patch

from services.users import (
    DEFAULT_AVATAR_URL,
    EMAIL_AUTH_PROVIDER,
    GOOGLE_AUTH_PROVIDER,
    create_user,
    delete_user_account,
    get_user_by_email,
    get_user_by_google_id,
    link_google_account,
)


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, *, fetchone_result=None):
        self.fetchone_result = fetchone_result
        self.executed = []
        self.closed = False

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))

    # 日本語: fetchone に関する処理の入口です。
    # English: Entry point for logic related to fetchone.
    def fetchone(self):
        result = self.fetchone_result
        self.fetchone_result = None
        return result

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: FakeConnection に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeConnection.
class FakeConnection:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    # 日本語: cursor に関する処理の入口です。
    # English: Entry point for logic related to cursor.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # 日本語: commit に関する処理の入口です。
    # English: Entry point for logic related to commit.
    def commit(self):
        self.committed = True

    # 日本語: rollback に関する処理の入口です。
    # English: Entry point for logic related to rollback.
    def rollback(self):
        self.rolled_back = True

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True

    # 日本語: コンテキスト開始時に必要な準備を行います。
    # English: Prepare the object when entering the context.
    def __enter__(self):
        return self

    # 日本語: コンテキスト終了時の後片付けを行います。
    # English: Clean up when leaving the context.
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


# 日本語: UserAuthProvidersTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to UserAuthProvidersTestCase.
class UserAuthProvidersTestCase(unittest.TestCase):
    # 日本語: test create user persists email provider in separate table のテスト検証を担当します。
    # English: Handle verifying test behavior for test create user persists email provider in separate table.
    def test_create_user_persists_email_provider_in_separate_table(self):
        fake_cursor = FakeCursor(fetchone_result=(321,))
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test create user uses default avatar when provider avatar url is too long のテスト検証を担当します。
    # English: Handle verifying test behavior for test create user uses default avatar when provider avatar url is too long.
    def test_create_user_uses_default_avatar_when_provider_avatar_url_is_too_long(self):
        fake_cursor = FakeCursor(fetchone_result=(322,))
        fake_conn = FakeConnection(fake_cursor)
        long_avatar_url = "https://lh3.googleusercontent.com/" + ("a" * 260)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.users.get_db_connection", return_value=fake_conn):
            user_id = create_user(
                "user@example.com",
                avatar_url=long_avatar_url,
                auth_provider=GOOGLE_AUTH_PROVIDER,
                provider_user_id="google-user-123",
                provider_email="user@example.com",
                is_verified=True,
            )

        self.assertEqual(user_id, 322)
        self.assertEqual(fake_cursor.executed[0][1][2], DEFAULT_AVATAR_URL)

    # 日本語: test link google account upserts google provider row のテスト検証を担当します。
    # English: Handle verifying test behavior for test link google account upserts google provider row.
    def test_link_google_account_upserts_google_provider_row(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.users.get_db_connection", return_value=fake_conn):
            link_google_account(7, "google-user-123", "user@example.com")

        self.assertTrue(fake_conn.committed)
        self.assertIn("INSERT INTO user_auth_providers", fake_cursor.executed[0][0])
        self.assertEqual(
            fake_cursor.executed[0][1],
            (7, GOOGLE_AUTH_PROVIDER, "google-user-123", "user@example.com"),
        )

    # 日本語: test get user by google id joins auth provider table のテスト検証を担当します。
    # English: Handle verifying test behavior for test get user by google id joins auth provider table.
    def test_get_user_by_google_id_joins_auth_provider_table(self):
        expected = {"id": 9, "email": "user@example.com", "provider_user_id": "google-user-123"}
        fake_cursor = FakeCursor(fetchone_result=expected)
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.users.get_db_connection", return_value=fake_conn):
            user = get_user_by_google_id("google-user-123")

        self.assertEqual(user, expected)
        self.assertIn("FROM user_auth_providers AS p JOIN users AS u ON u.id = p.user_id", fake_cursor.executed[0][0])
        self.assertEqual(fake_cursor.executed[0][1], (GOOGLE_AUTH_PROVIDER, "google-user-123"))

    # 日本語: test get user by email keeps google provider metadata available のテスト検証を担当します。
    # English: Handle verifying test behavior for test get user by email keeps google provider metadata available.
    def test_get_user_by_email_keeps_google_provider_metadata_available(self):
        expected = {"id": 10, "email": "user@example.com", "provider_user_id": "google-user-999"}
        fake_cursor = FakeCursor(fetchone_result=expected)
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.users.get_db_connection", return_value=fake_conn):
            user = get_user_by_email("user@example.com")

        self.assertEqual(user, expected)
        self.assertIn("LEFT JOIN user_auth_providers AS gap", fake_cursor.executed[0][0])
        self.assertEqual(fake_cursor.executed[0][1], (GOOGLE_AUTH_PROVIDER, "user@example.com"))

    # 日本語: test delete user account removes user owned data before user のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete user account removes user owned data before user.
    def test_delete_user_account_removes_user_owned_data_before_user(self):
        fake_cursor = FakeCursor(fetchone_result=(7,))
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.users.get_db_connection", return_value=fake_conn):
            deleted = delete_user_account(7)

        self.assertTrue(deleted)
        self.assertTrue(fake_conn.committed)
        self.assertFalse(fake_conn.rolled_back)
        self.assertIn("SELECT id FROM users WHERE id = %s FOR UPDATE", fake_cursor.executed[0][0])
        self.assertIn("DELETE FROM memo_entries WHERE user_id = %s", [query for query, _ in fake_cursor.executed])
        self.assertEqual(fake_cursor.executed[-1], ("DELETE FROM users WHERE id = %s", (7,)))

    # 日本語: test delete user account returns false when user missing のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete user account returns false when user missing.
    def test_delete_user_account_returns_false_when_user_missing(self):
        fake_cursor = FakeCursor(fetchone_result=None)
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.users.get_db_connection", return_value=fake_conn):
            deleted = delete_user_account(7)

        self.assertFalse(deleted)
        self.assertFalse(fake_conn.committed)
        self.assertTrue(fake_conn.rolled_back)
        self.assertEqual(len(fake_cursor.executed), 1)


if __name__ == "__main__":
    unittest.main()
