import os
import unittest
from unittest.mock import patch

from services import auth_limits
from tests.helpers.request_helpers import build_request


def make_request(*, headers=None):
    return build_request(
        method="POST",
        path="/api/chat",
        session={},
        headers=headers or [],
    )


class GuestChatLimitTestCase(unittest.TestCase):
    def setUp(self):
        self.original_guest_limit = os.environ.get("GUEST_CHAT_DAILY_LIMIT")
        auth_limits.clear_in_memory_rate_limit_state()

    def tearDown(self):
        if self.original_guest_limit is None:
            os.environ.pop("GUEST_CHAT_DAILY_LIMIT", None)
        else:
            os.environ["GUEST_CHAT_DAILY_LIMIT"] = self.original_guest_limit
        auth_limits.clear_in_memory_rate_limit_state()

    def test_guest_chat_limit_blocks_after_reaching_cap(self):
        os.environ["GUEST_CHAT_DAILY_LIMIT"] = "2"
        request = make_request(headers=[(b"x-forwarded-for", b"198.51.100.10")])

        with patch("services.auth_limits.get_redis_client", return_value=None):
            first = auth_limits.consume_guest_chat_daily_limit(request)
            second = auth_limits.consume_guest_chat_daily_limit(request)
            third = auth_limits.consume_guest_chat_daily_limit(request)

        self.assertEqual(first, (True, None))
        self.assertEqual(second, (True, None))
        self.assertEqual(third, (False, "1日2回までです"))

    def test_guest_chat_limit_invalid_env_falls_back_to_default(self):
        os.environ["GUEST_CHAT_DAILY_LIMIT"] = "invalid"
        request = make_request(headers=[(b"x-forwarded-for", b"203.0.113.11")])

        with patch("services.auth_limits.get_redis_client", return_value=None):
            for _ in range(auth_limits.DEFAULT_GUEST_CHAT_DAILY_LIMIT):
                allowed, message = auth_limits.consume_guest_chat_daily_limit(request)
                self.assertTrue(allowed)
                self.assertIsNone(message)

            blocked = auth_limits.consume_guest_chat_daily_limit(request)

        self.assertEqual(
            blocked,
            (False, f"1日{auth_limits.DEFAULT_GUEST_CHAT_DAILY_LIMIT}回までです"),
        )

    def test_guest_chat_limit_uses_forwarded_ip_for_identifier(self):
        os.environ["GUEST_CHAT_DAILY_LIMIT"] = "1"
        request_a = make_request(headers=[(b"x-forwarded-for", b"203.0.113.101, 10.0.0.1")])
        request_b = make_request(headers=[(b"x-forwarded-for", b"203.0.113.102, 10.0.0.1")])

        with patch("services.auth_limits.get_redis_client", return_value=None):
            first_a = auth_limits.consume_guest_chat_daily_limit(request_a)
            second_a = auth_limits.consume_guest_chat_daily_limit(request_a)
            first_b = auth_limits.consume_guest_chat_daily_limit(request_b)

        self.assertEqual(first_a, (True, None))
        self.assertEqual(second_a, (False, "1日1回までです"))
        self.assertEqual(first_b, (True, None))


if __name__ == "__main__":
    unittest.main()
