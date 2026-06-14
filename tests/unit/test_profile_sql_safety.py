import unittest
from unittest.mock import patch

from blueprints.chat.profile import _update_user_profile
from tests.helpers.db_helpers import TransactionTrackingConnection


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, fail_on_execute=False):
        self.fail_on_execute = fail_on_execute
        self.executed = []
        self.closed = False

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        self.executed.append((query, params))
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self.fail_on_execute:
            raise RuntimeError("db error")

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: FakeConnection に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeConnection.
class FakeConnection(TransactionTrackingConnection):
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, fail_on_execute=False):
        super().__init__(FakeCursor(fail_on_execute=fail_on_execute))


# 日本語: ProfileSQLSafetyTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ProfileSQLSafetyTestCase.
class ProfileSQLSafetyTestCase(unittest.TestCase):
    # 日本語: test update user profile uses parameterized static sql のテスト検証を担当します。
    # English: Handle verifying test behavior for test update user profile uses parameterized static sql.
    def test_update_user_profile_uses_parameterized_static_sql(self):
        fake_connection = FakeConnection()
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "blueprints.chat.profile.get_db_connection",
            return_value=fake_connection,
        ):
            _update_user_profile(
                user_id=10,
                username="alice",
                email="alice@example.com",
                bio="hello",
                avatar_url=None,
                llm_profile_context="日本語で簡潔に答えてください",
            )

        self.assertTrue(fake_connection.committed)
        self.assertFalse(fake_connection.rolled_back)
        self.assertTrue(fake_connection.closed)
        self.assertTrue(fake_connection._cursor.closed)
        self.assertEqual(len(fake_connection._cursor.executed), 1)
        query, params = fake_connection._cursor.executed[0]
        self.assertIn("UPDATE users", query)
        self.assertIn("llm_profile_context = %s", query)
        self.assertIn("avatar_url = COALESCE(%s, avatar_url)", query)
        # The email column must never be touched by the generic profile
        # update — email changes go through the verified email-change flow.
        self.assertNotIn("email = %s", query)
        self.assertEqual(
            params,
            (
                "alice",
                "hello",
                "日本語で簡潔に答えてください",
                None,
                10,
            ),
        )
        self.assertNotIn("alice@example.com", query)

    # 日本語: test update user profile passes avatar url as parameter のテスト検証を担当します。
    # English: Handle verifying test behavior for test update user profile passes avatar url as parameter.
    def test_update_user_profile_passes_avatar_url_as_parameter(self):
        fake_connection = FakeConnection()
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "blueprints.chat.profile.get_db_connection",
            return_value=fake_connection,
        ):
            _update_user_profile(
                user_id=11,
                username="bob",
                email="bob@example.com",
                bio="bio",
                avatar_url="/static/uploads/bob.png",
                llm_profile_context="箇条書きを優先",
            )

        query, params = fake_connection._cursor.executed[0]
        self.assertIn("UPDATE users", query)
        self.assertNotIn("email = %s", query)
        self.assertEqual(
            params,
            (
                "bob",
                "bio",
                "箇条書きを優先",
                "/static/uploads/bob.png",
                11,
            ),
        )

    # 日本語: test update user profile rolls back on failure のテスト検証を担当します。
    # English: Handle verifying test behavior for test update user profile rolls back on failure.
    def test_update_user_profile_rolls_back_on_failure(self):
        fake_connection = FakeConnection(fail_on_execute=True)
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "blueprints.chat.profile.get_db_connection",
            return_value=fake_connection,
        ):
            with self.assertRaises(RuntimeError):
                _update_user_profile(
                    user_id=12,
                    username="charlie",
                    email="charlie@example.com",
                    bio="bio",
                    avatar_url=None,
                    llm_profile_context="丁寧に答える",
                )

        self.assertFalse(fake_connection.committed)
        self.assertTrue(fake_connection.rolled_back)
        self.assertTrue(fake_connection.closed)
        self.assertTrue(fake_connection._cursor.closed)


if __name__ == "__main__":
    unittest.main()
