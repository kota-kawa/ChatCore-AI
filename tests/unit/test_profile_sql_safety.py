import unittest
from unittest.mock import patch

from blueprints.chat.profile import _update_user_profile
from tests.helpers.db_helpers import TransactionTrackingConnection


class FakeCursor:
    def __init__(self, fail_on_execute=False):
        self.fail_on_execute = fail_on_execute
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if self.fail_on_execute:
            raise RuntimeError("db error")

    def close(self):
        self.closed = True


class FakeConnection(TransactionTrackingConnection):
    def __init__(self, fail_on_execute=False):
        super().__init__(FakeCursor(fail_on_execute=fail_on_execute))


class ProfileSQLSafetyTestCase(unittest.TestCase):
    def test_update_user_profile_uses_parameterized_static_sql(self):
        fake_connection = FakeConnection()
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
        self.assertEqual(
            params,
            (
                "alice",
                "alice@example.com",
                "hello",
                "日本語で簡潔に答えてください",
                None,
                10,
            ),
        )
        self.assertNotIn("alice@example.com", query)

    def test_update_user_profile_passes_avatar_url_as_parameter(self):
        fake_connection = FakeConnection()
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
        self.assertEqual(
            params,
            (
                "bob",
                "bob@example.com",
                "bio",
                "箇条書きを優先",
                "/static/uploads/bob.png",
                11,
            ),
        )

    def test_update_user_profile_rolls_back_on_failure(self):
        fake_connection = FakeConnection(fail_on_execute=True)
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
