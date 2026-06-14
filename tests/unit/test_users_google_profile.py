import unittest
from unittest.mock import patch

from services.users import update_user_profile_from_google_if_unset


# テスト用の疑似DBカーソルクラス。
# Mock database cursor class for testing.
class FakeCursor:
    # 現在のユーザープロファイル情報を保持して初期化します。
    # Initialize the fake cursor with the current user profile.
    def __init__(self, current_profile):
        self.current_profile = dict(current_profile)
        self.executed = []
        self._fetchone_result = None
        self.closed = False

    # クエリを実行し、クエリ内容に応じて結果の設定やプロファイルの更新を疑似的に行います。
    # Simulate query execution, setting query results or updating profile accordingly.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))

        # ユーザー取得クエリの場合、現在のプロファイルをセット
        # Set current profile if it is a user retrieval query
        if "SELECT username, avatar_url FROM users WHERE id = %s" in normalized:
            self._fetchone_result = dict(self.current_profile)
            return

        # プロファイル更新クエリの場合、現在のプロファイルを引数の値で更新
        # Update current profile with parameters if it is an update query
        if "UPDATE users SET username = %s, avatar_url = %s WHERE id = %s" in normalized:
            self.current_profile["username"] = params[0]
            self.current_profile["avatar_url"] = params[1]
            self._fetchone_result = None
            return

        self._fetchone_result = None

    # クエリの実行結果から1レコード分（疑似的）を取得します。
    # Fetch the mock single record result of the query.
    def fetchone(self):
        result = self._fetchone_result
        self._fetchone_result = None
        return result

    # カーソルを閉じます。
    # Close the cursor.
    def close(self):
        self.closed = True


# テスト用の疑似DBコネクションクラス。
# Mock database connection class for testing.
class FakeConnection:
    # インスタンス生成時に必要な初期状態を設定します。
    # Initialize the required instance state when the object is created.
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.closed = False

    # カーソルを返却します。
    # Return the cursor.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # コミットされたことを記録します。
    # Commit the current mock transaction.
    def commit(self):
        self.committed = True

    # コネクションを閉じます。
    # Close the connection.
    def close(self):
        self.closed = True

    # コンテキスト開始時に必要な準備を行います。
    # Prepare the object when entering the context.
    def __enter__(self):
        return self

    # コンテキスト終了時の後片付けを行います。
    # Clean up when leaving the context.
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


# Googleログイン時に、デフォルトのプロファイル情報をGoogleのプロフィール情報で更新する処理のテスト。
# Test class to check user profile sync with Google profile details on Google login.
class GoogleProfileSyncTestCase(unittest.TestCase):
    # ユーザー名とアバター画像がデフォルト状態の場合、Googleの情報で更新されることを検証します。
    # Verify that default username and avatar are updated using Google profile data.
    def test_updates_default_username_and_avatar_from_google(self):
        fake_cursor = FakeCursor(
            {"username": "ユーザー", "avatar_url": "/static/user-icon.png"}
        )
        fake_conn = FakeConnection(fake_cursor)

        # DB接続をモックして同期処理を実行
        # Mock the DB connection and run sync logic
        with patch("services.users.get_db_connection", return_value=fake_conn):
            update_user_profile_from_google_if_unset(
                7,
                name="Alice Example",
                picture="https://example.com/alice.png",
            )

        self.assertTrue(fake_conn.committed)
        self.assertTrue(fake_conn.closed)
        self.assertTrue(fake_cursor.closed)
        self.assertEqual(fake_cursor.current_profile["username"], "Alice Example")
        self.assertEqual(
            fake_cursor.current_profile["avatar_url"],
            "https://example.com/alice.png",
        )

    # すでにカスタムされたプロフィールが設定されている場合、Googleの情報で上書きされないことを検証します。
    # Verify that custom user profile details are preserved and not overwritten by Google profile data.
    def test_preserves_existing_custom_profile_values(self):
        fake_cursor = FakeCursor(
            {"username": "Custom Name", "avatar_url": "/static/uploads/custom.png"}
        )
        fake_conn = FakeConnection(fake_cursor)

        # DB接続をモックして同期処理を実行
        # Mock the DB connection and run sync logic
        with patch("services.users.get_db_connection", return_value=fake_conn):
            update_user_profile_from_google_if_unset(
                8,
                name="Google Name",
                picture="https://example.com/google.png",
            )

        self.assertTrue(fake_conn.committed)
        self.assertEqual(fake_cursor.current_profile["username"], "Custom Name")
        self.assertEqual(
            fake_cursor.current_profile["avatar_url"],
            "/static/uploads/custom.png",
        )


if __name__ == "__main__":
    unittest.main()
