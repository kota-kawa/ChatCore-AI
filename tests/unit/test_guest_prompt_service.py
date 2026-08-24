import unittest
from unittest.mock import patch

from services.guest_prompt_service import (
    GUEST_PROMPT_SESSION_KEY,
    GuestPromptLimitExceeded,
    claim_guest_prompts_for_user,
    create_guest_shared_prompt,
    get_or_create_guest_prompt_token,
)
from services.request_models import SharedPromptCreateRequest


class FakeCursor:
    def __init__(self, results=None):
        self.executed = []
        self.results = list(results or [])
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.results.pop(0) if self.results else None

    def fetchall(self):
        return self.results.pop(0) if self.results else []

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, results=None):
        self.db_cursor = FakeCursor(results)
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self, **_kwargs):
        return self.db_cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class GuestPromptServiceTestCase(unittest.TestCase):
    @staticmethod
    def _payload():
        return SharedPromptCreateRequest.model_validate(
            {
                "title": "Guest text prompt",
                "description": "A short guest post description.",
                "content": "Write a concise introduction.",
                "content_format": "prompt",
                "media_type": "text",
            }
        )

    def test_session_token_is_random_and_reused(self):
        session = {}

        token = get_or_create_guest_prompt_token(session)

        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(session[GUEST_PROMPT_SESSION_KEY], token)
        self.assertEqual(get_or_create_guest_prompt_token(session), token)

    def test_creation_locks_cookie_and_ip_then_persists_only_hashes(self):
        connection = FakeConnection(results=[None, {"id": 88}])
        token = "guest-token-which-is-long-enough-to-be-valid"
        ip_address = "203.0.113.10"

        with patch("services.guest_prompt_service.get_db_connection", return_value=connection):
            prompt_id = create_guest_shared_prompt(token, ip_address, self._payload())

        self.assertEqual(prompt_id, 88)
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        prompt_sql, prompt_params = connection.db_cursor.executed[3]
        self.assertIn("description", prompt_sql)
        self.assertEqual(prompt_params[-1], "A short guest post description.")
        quota_sql, quota_params = connection.db_cursor.executed[2]
        self.assertIn("guest_cookie_hash = %s OR client_ip_hash = %s", quota_sql)
        self.assertNotIn(token, quota_params)
        self.assertNotIn(ip_address, quota_params)
        self.assertEqual([len(value) for value in quota_params], [64, 64])
        submission_sql, submission_params = connection.db_cursor.executed[-1]
        self.assertIn("INSERT INTO guest_prompt_submissions", submission_sql)
        self.assertEqual(submission_params[0], 88)
        self.assertEqual([len(value) for value in submission_params[1:]], [64, 64])

    def test_recent_cookie_or_ip_submission_rejects_before_prompt_insert(self):
        connection = FakeConnection(results=[{"retry_after": 321}])

        with patch("services.guest_prompt_service.get_db_connection", return_value=connection):
            with self.assertRaises(GuestPromptLimitExceeded) as raised:
                create_guest_shared_prompt(
                    "guest-token-which-is-long-enough-to-be-valid",
                    "203.0.113.10",
                    self._payload(),
                )

        self.assertEqual(raised.exception.retry_after, 321)
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)
        executed_sql = "\n".join(sql for sql, _ in connection.db_cursor.executed)
        self.assertNotIn("INSERT INTO prompts", executed_sql)

    def test_claim_assigns_only_matching_unclaimed_prompts(self):
        connection = FakeConnection(results=[[(88,), (91,)]])

        with patch("services.guest_prompt_service.get_db_connection", return_value=connection):
            prompt_ids = claim_guest_prompts_for_user(
                7,
                "guest-token-which-is-long-enough-to-be-valid",
            )

        self.assertEqual(prompt_ids, [88, 91])
        self.assertTrue(connection.committed)
        sql, params = connection.db_cursor.executed[0]
        self.assertIn("gps.guest_cookie_hash = %s", sql)
        self.assertIn("gps.claimed_at IS NULL", sql)
        self.assertIn("p.user_id IS NULL", sql)
        self.assertEqual(params[0], 7)
        self.assertEqual(params[1], 7)
        self.assertEqual(len(params[2]), 64)
        self.assertEqual(params[3], 7)


if __name__ == "__main__":
    unittest.main()
