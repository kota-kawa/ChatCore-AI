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


# 日本語: テスト用のフェイクDBカーソルクラス。クエリの実行履歴と1件取得結果を追跡します。
# English: Fake DB cursor class for testing. Tracks executed queries and single-row fetch results.
class FakeCursor:
    # 日本語: 取得結果のデフォルト値を設定し、実行済みクエリリストとクローズ状態を初期化します。
    # English: Initialize with a default fetchone result, empty executed list, and closed flag.
    def __init__(self, *, fetchone_result=None):
        self.fetchone_result = fetchone_result
        self.executed = []
        self.closed = False

    # 日本語: クエリと引数を正規化し、実行済みリストに記録します。
    # English: Normalize the query and record it along with params in the executed list.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))

    # 日本語: 設定された1件の取得結果を返し、次回以降はNoneを返します。
    # English: Return the set fetchone result once, then return None on subsequent calls.
    def fetchone(self):
        result = self.fetchone_result
        self.fetchone_result = None
        return result

    # 日本語: カーソルをクローズ済みとしてマークします。
    # English: Mark the cursor as closed.
    def close(self):
        self.closed = True


# 日本語: テスト用のフェイクDBコネクションクラス。コミット・ロールバック・クローズの状態を追跡します。
# English: Fake DB connection class for testing. Tracks commit, rollback, and close states.
class FakeConnection:
    # 日本語: カーソルを受け取り、トランザクション追跡フラグを初期化します。
    # English: Accept a cursor and initialize transaction tracking flags.
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    # 日本語: フェイクカーソルを返します。
    # English: Return the fake cursor.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # 日本語: コミット済みフラグを立てます。
    # English: Mark the connection as committed.
    def commit(self):
        self.committed = True

    # 日本語: ロールバック済みフラグを立てます。
    # English: Mark the connection as rolled back.
    def rollback(self):
        self.rolled_back = True

    # 日本語: クローズ済みフラグを立てます。
    # English: Mark the connection as closed.
    def close(self):
        self.closed = True

    # 日本語: コンテキストマネージャの開始時に自身を返します。
    # English: Return self when entering a context manager block.
    def __enter__(self):
        return self

    # 日本語: コンテキストマネージャの終了時にコネクションをクローズします。
    # English: Close the connection when exiting a context manager block.
    def __exit__(self, _exc_type, _exc, _tb):
        self.close()
        return False


# 日本語: ユーザー認証プロバイダー関連のDB操作（作成・取得・リンク・削除）をテストするクラス。
# English: Test class for user auth provider related DB operations (create, get, link, delete).
class UserAuthProvidersTestCase(unittest.TestCase):
    # 日本語: create_user がユーザーレコードとともに、メールプロバイダーのauth_providersレコードを別テーブルに挿入することを検証します。
    # English: Verify that create_user inserts a user record and a corresponding email auth_providers record into a separate table.
    def test_create_user_persists_email_provider_in_separate_table(self):
        fake_cursor = FakeCursor(fetchone_result=(321,))
        fake_conn = FakeConnection(fake_cursor)

        with patch("services.users.get_db_connection", return_value=fake_conn):
            user_id = create_user("user@example.com")

        # 日本語: ユーザーIDが正しく返され、コミットされ、両テーブルへの挿入が実行されたことを確認
        # English: Confirm user_id is returned correctly, committed, and inserts ran for both tables
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

    # 日本語: アバターURLが長すぎる場合にデフォルトアバターURLが使用されることを検証します。
    # English: Verify that the default avatar URL is used when the provider's avatar URL is too long.
    def test_create_user_uses_default_avatar_when_provider_avatar_url_is_too_long(self):
        fake_cursor = FakeCursor(fetchone_result=(322,))
        fake_conn = FakeConnection(fake_cursor)
        # 日本語: 260文字を超える長いアバターURLを用意
        # English: Prepare an avatar URL exceeding 260 characters
        long_avatar_url = "https://lh3.googleusercontent.com/" + ("a" * 260)

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
        # 日本語: デフォルトURLが使われていることを確認
        # English: Confirm the default avatar URL was used instead
        self.assertEqual(fake_cursor.executed[0][1][2], DEFAULT_AVATAR_URL)

    # 日本語: link_google_account がユーザーIDとGoogleプロバイダー情報をUPSERTすることを検証します。
    # English: Verify that link_google_account upserts the user ID with Google provider info.
    def test_link_google_account_upserts_google_provider_row(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        with patch("services.users.get_db_connection", return_value=fake_conn):
            link_google_account(7, "google-user-123", "user@example.com")

        # 日本語: 正しいパラメータでUPSERTが実行され、コミットされていることを確認
        # English: Confirm the UPSERT was executed with correct params and committed
        self.assertTrue(fake_conn.committed)
        self.assertIn("INSERT INTO user_auth_providers", fake_cursor.executed[0][0])
        self.assertEqual(
            fake_cursor.executed[0][1],
            (7, GOOGLE_AUTH_PROVIDER, "google-user-123", "user@example.com"),
        )

    # 日本語: get_user_by_google_id がauth_providersテーブルとのJOINクエリを使ってユーザーを取得することを検証します。
    # English: Verify that get_user_by_google_id retrieves a user via a JOIN query with the auth_providers table.
    def test_get_user_by_google_id_joins_auth_provider_table(self):
        expected = {"id": 9, "email": "user@example.com", "provider_user_id": "google-user-123"}
        fake_cursor = FakeCursor(fetchone_result=expected)
        fake_conn = FakeConnection(fake_cursor)

        with patch("services.users.get_db_connection", return_value=fake_conn):
            user = get_user_by_google_id("google-user-123")

        self.assertEqual(user, expected)
        # 日本語: JOINクエリが正しいテーブルとプロバイダーで実行されていることを確認
        # English: Confirm the JOIN query was executed with the correct table and provider
        self.assertIn("FROM user_auth_providers AS p JOIN users AS u ON u.id = p.user_id", fake_cursor.executed[0][0])
        self.assertEqual(fake_cursor.executed[0][1], (GOOGLE_AUTH_PROVIDER, "google-user-123"))

    # 日本語: get_user_by_email がGoogleプロバイダーのメタデータも取得できるようにLEFT JOINを使うことを検証します。
    # English: Verify that get_user_by_email uses LEFT JOIN to also fetch Google provider metadata.
    def test_get_user_by_email_keeps_google_provider_metadata_available(self):
        expected = {"id": 10, "email": "user@example.com", "provider_user_id": "google-user-999"}
        fake_cursor = FakeCursor(fetchone_result=expected)
        fake_conn = FakeConnection(fake_cursor)

        with patch("services.users.get_db_connection", return_value=fake_conn):
            user = get_user_by_email("user@example.com")

        self.assertEqual(user, expected)
        # 日本語: LEFT JOINが使われGoogleプロバイダーでフィルタリングされていることを確認
        # English: Confirm LEFT JOIN was used and filtered by Google provider
        self.assertIn("LEFT JOIN user_auth_providers AS gap", fake_cursor.executed[0][0])
        self.assertEqual(fake_cursor.executed[0][1], (GOOGLE_AUTH_PROVIDER, "user@example.com"))

    # 日本語: delete_user_account がユーザー自身を削除する前に関連データを削除することを検証します。
    # English: Verify that delete_user_account removes all user-owned data before deleting the user record.
    def test_delete_user_account_removes_user_owned_data_before_user(self):
        fake_cursor = FakeCursor(fetchone_result=(7,))
        fake_conn = FakeConnection(fake_cursor)

        with patch("services.users.get_db_connection", return_value=fake_conn):
            deleted = delete_user_account(7)

        # 日本語: 関連データ削除後にユーザー本体のDELETEが最後に実行されていることを確認
        # English: Confirm user-owned data was deleted first, then the user record last
        self.assertTrue(deleted)
        self.assertTrue(fake_conn.committed)
        self.assertFalse(fake_conn.rolled_back)
        self.assertIn("SELECT id FROM users WHERE id = %s FOR UPDATE", fake_cursor.executed[0][0])
        self.assertIn("DELETE FROM memo_entries WHERE user_id = %s", [query for query, _ in fake_cursor.executed])
        self.assertEqual(fake_cursor.executed[-1], ("DELETE FROM users WHERE id = %s", (7,)))

    # 日本語: 削除対象のユーザーが存在しない場合にFalseを返し、ロールバックされることを検証します。
    # English: Verify that delete_user_account returns False and rolls back when the user is not found.
    def test_delete_user_account_returns_false_when_user_missing(self):
        fake_cursor = FakeCursor(fetchone_result=None)
        fake_conn = FakeConnection(fake_cursor)

        with patch("services.users.get_db_connection", return_value=fake_conn):
            deleted = delete_user_account(7)

        # 日本語: 存在しないユーザーにはFalseを返し、ロールバックのみが実行されることを確認
        # English: Confirm False is returned and only rollback was triggered for a missing user
        self.assertFalse(deleted)
        self.assertFalse(fake_conn.committed)
        self.assertTrue(fake_conn.rolled_back)
        self.assertEqual(len(fake_cursor.executed), 1)


if __name__ == "__main__":
    unittest.main()
