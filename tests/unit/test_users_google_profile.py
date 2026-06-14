import unittest
from unittest.mock import patch

from services.users import update_user_profile_from_google_if_unset


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, current_profile):
        self.current_profile = dict(current_profile)
        self.executed = []
        self._fetchone_result = None
        self.closed = False

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if "SELECT username, avatar_url FROM users WHERE id = %s" in normalized:
            self._fetchone_result = dict(self.current_profile)
            return

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if "UPDATE users SET username = %s, avatar_url = %s WHERE id = %s" in normalized:
            self.current_profile["username"] = params[0]
            self.current_profile["avatar_url"] = params[1]
            self._fetchone_result = None
            return

        self._fetchone_result = None

    # 日本語: fetchone に関する処理の入口です。
    # English: Entry point for logic related to fetchone.
    def fetchone(self):
        result = self._fetchone_result
        self._fetchone_result = None
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
        self.closed = False

    # 日本語: cursor に関する処理の入口です。
    # English: Entry point for logic related to cursor.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # 日本語: commit に関する処理の入口です。
    # English: Entry point for logic related to commit.
    def commit(self):
        self.committed = True

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


# 日本語: GoogleProfileSyncTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to GoogleProfileSyncTestCase.
class GoogleProfileSyncTestCase(unittest.TestCase):
    # 日本語: test updates default username and avatar from google のテスト検証を担当します。
    # English: Handle verifying test behavior for test updates default username and avatar from google.
    def test_updates_default_username_and_avatar_from_google(self):
        fake_cursor = FakeCursor(
            {"username": "ユーザー", "avatar_url": "/static/user-icon.png"}
        )
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test preserves existing custom profile values のテスト検証を担当します。
    # English: Handle verifying test behavior for test preserves existing custom profile values.
    def test_preserves_existing_custom_profile_values(self):
        fake_cursor = FakeCursor(
            {"username": "Custom Name", "avatar_url": "/static/uploads/custom.png"}
        )
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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
