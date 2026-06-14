import unittest
from unittest.mock import patch

from blueprints.chat.profile import _update_user_profile
from tests.helpers.db_helpers import TransactionTrackingConnection


# 日本語: テスト用の擬似Fake Cursorクラスです。
# English: Mock Fake Cursor class for testing.
class FakeCursor:
    def __init__(self, fail_on_execute=False):
        self.fail_on_execute = fail_on_execute
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((query, params))
        # 日本語: 条件に基づいて処理の流れを切り替えます。
        # English: Switch the execution flow based on the condition.
        if self.fail_on_execute:
            raise RuntimeError("db error")

    # 日本語: 後処理を実行します。
# English: Perform cleanup operations.
    def close(self):
        self.closed = True


# 日本語: テスト用の擬似Fake Connectionクラスです。
# English: Mock Fake Connection class for testing.
class FakeConnection(TransactionTrackingConnection):
    def __init__(self, fail_on_execute=False):
        super().__init__(FakeCursor(fail_on_execute=fail_on_execute))


# 日本語: Profile S Q L Safetyの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Profile S Q L Safety.
class ProfileSQLSafetyTestCase(unittest.TestCase):
    # 日本語: 更新ユーザープロフィールusesパラメータ化された静的SQLことを検証します。
    # English: Verify that update user profile uses parameterized static sql.
    def test_update_user_profile_uses_parameterized_static_sql(self):
        fake_connection = FakeConnection()
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
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

    # 日本語: 更新ユーザープロフィール通過するアバターURLasパラメータことを検証します。
    # English: Verify that update user profile passes avatar url as parameter.
    def test_update_user_profile_passes_avatar_url_as_parameter(self):
        fake_connection = FakeConnection()
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
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

    # 日本語: 失敗における、更新ユーザープロフィールロールバックことを検証します。
    # English: Verify that update user profile rolls back on failure.
    def test_update_user_profile_rolls_back_on_failure(self):
        fake_connection = FakeConnection(fail_on_execute=True)
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
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
