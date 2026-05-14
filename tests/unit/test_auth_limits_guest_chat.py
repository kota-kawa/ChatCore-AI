import os
import unittest
from unittest.mock import patch

from services import auth_limits
from tests.helpers.request_helpers import build_request


def make_request(*, headers=None, client_host="testclient"):
    request = build_request(
        method="POST",
        path="/api/chat",
        session={},
        headers=headers or [],
    )
    request.scope["client"] = (client_host, 50000)
    return request


class GuestChatLimitTestCase(unittest.TestCase):
    def setUp(self):
        self.original_guest_limit = os.environ.get("GUEST_CHAT_DAILY_LIMIT")
        self.original_trusted_proxies = os.environ.get("TRUSTED_PROXY_IPS")
        self.original_admin_login_limit = os.environ.get("ADMIN_LOGIN_PER_IP_LIMIT")
        os.environ["TRUSTED_PROXY_IPS"] = "127.0.0.1,::1"
        auth_limits.clear_in_memory_rate_limit_state()

    def tearDown(self):
        if self.original_guest_limit is None:
            os.environ.pop("GUEST_CHAT_DAILY_LIMIT", None)
        else:
            os.environ["GUEST_CHAT_DAILY_LIMIT"] = self.original_guest_limit
        if self.original_trusted_proxies is None:
            os.environ.pop("TRUSTED_PROXY_IPS", None)
        else:
            os.environ["TRUSTED_PROXY_IPS"] = self.original_trusted_proxies
        if self.original_admin_login_limit is None:
            os.environ.pop("ADMIN_LOGIN_PER_IP_LIMIT", None)
        else:
            os.environ["ADMIN_LOGIN_PER_IP_LIMIT"] = self.original_admin_login_limit
        auth_limits.clear_in_memory_rate_limit_state()

    def test_guest_chat_limit_blocks_after_reaching_cap(self):
        os.environ["GUEST_CHAT_DAILY_LIMIT"] = "2"
        request = make_request(
            headers=[(b"x-forwarded-for", b"198.51.100.10")],
            client_host="127.0.0.1",
        )

        with patch("services.auth_limits.get_redis_client", return_value=None):
            first = auth_limits.consume_guest_chat_daily_limit(request)
            second = auth_limits.consume_guest_chat_daily_limit(request)
            third = auth_limits.consume_guest_chat_daily_limit(request)

        self.assertEqual(first, (True, None))
        self.assertEqual(second, (True, None))
        self.assertEqual(third, (False, "1日2回までです"))

    def test_guest_chat_limit_invalid_env_falls_back_to_default(self):
        os.environ["GUEST_CHAT_DAILY_LIMIT"] = "invalid"
        request = make_request(
            headers=[(b"x-forwarded-for", b"203.0.113.11")],
            client_host="127.0.0.1",
        )

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
        request_a = make_request(
            headers=[(b"x-forwarded-for", b"203.0.113.101")],
            client_host="127.0.0.1",
        )
        request_b = make_request(
            headers=[(b"x-forwarded-for", b"203.0.113.102")],
            client_host="127.0.0.1",
        )

        with patch("services.auth_limits.get_redis_client", return_value=None):
            first_a = auth_limits.consume_guest_chat_daily_limit(request_a)
            second_a = auth_limits.consume_guest_chat_daily_limit(request_a)
            first_b = auth_limits.consume_guest_chat_daily_limit(request_b)

        self.assertEqual(first_a, (True, None))
        self.assertEqual(second_a, (False, "1日1回までです"))
        self.assertEqual(first_b, (True, None))

    def test_guest_chat_limit_ignores_forwarded_for_from_untrusted_client(self):
        os.environ["GUEST_CHAT_DAILY_LIMIT"] = "1"
        request_a = make_request(
            headers=[(b"x-forwarded-for", b"198.51.100.201")],
            client_host="203.0.113.50",
        )
        request_b = make_request(
            headers=[(b"x-forwarded-for", b"198.51.100.202")],
            client_host="203.0.113.50",
        )

        with patch("services.auth_limits.get_redis_client", return_value=None):
            first = auth_limits.consume_guest_chat_daily_limit(request_a)
            second = auth_limits.consume_guest_chat_daily_limit(request_b)

        self.assertEqual(first, (True, None))
        self.assertEqual(second, (False, "1日1回までです"))

    def test_guest_chat_limit_uses_rightmost_untrusted_forwarded_ip(self):
        os.environ["GUEST_CHAT_DAILY_LIMIT"] = "1"
        request_a = make_request(
            headers=[(b"x-forwarded-for", b"198.51.100.250, 203.0.113.60")],
            client_host="127.0.0.1",
        )
        request_b = make_request(
            headers=[(b"x-forwarded-for", b"198.51.100.251, 203.0.113.60")],
            client_host="127.0.0.1",
        )

        with patch("services.auth_limits.get_redis_client", return_value=None):
            first = auth_limits.consume_guest_chat_daily_limit(request_a)
            second = auth_limits.consume_guest_chat_daily_limit(request_b)

        self.assertEqual(first, (True, None))
        self.assertEqual(second, (False, "1日1回までです"))

    def test_verification_attempt_limit_blocks_after_per_email_cap(self):
        # Cross-session brute-force: same email submitted from rotating IPs
        # still hits the per-email cap.
        os.environ["VERIFICATION_ATTEMPT_PER_EMAIL_LIMIT"] = "3"
        os.environ["VERIFICATION_ATTEMPT_PER_IP_LIMIT"] = "10000"
        os.environ["VERIFICATION_ATTEMPT_WINDOW_SECONDS"] = "3600"

        try:
            with patch("services.auth_limits.get_redis_client", return_value=None):
                results = []
                for i in range(4):
                    request = make_request(
                        headers=[(b"x-forwarded-for", f"203.0.113.{20 + i}".encode())],
                        client_host="127.0.0.1",
                    )
                    results.append(
                        auth_limits.consume_verification_attempt_limit(
                            request, "victim@example.com"
                        )
                    )
        finally:
            os.environ.pop("VERIFICATION_ATTEMPT_PER_EMAIL_LIMIT", None)
            os.environ.pop("VERIFICATION_ATTEMPT_PER_IP_LIMIT", None)
            os.environ.pop("VERIFICATION_ATTEMPT_WINDOW_SECONDS", None)

        self.assertEqual(results[0][0], True)
        self.assertEqual(results[1][0], True)
        self.assertEqual(results[2][0], True)
        self.assertEqual(results[3][0], False)
        self.assertIn("試行回数", results[3][1] or "")

    def test_verification_attempt_limit_blocks_after_per_ip_cap(self):
        os.environ["VERIFICATION_ATTEMPT_PER_EMAIL_LIMIT"] = "10000"
        os.environ["VERIFICATION_ATTEMPT_PER_IP_LIMIT"] = "3"
        os.environ["VERIFICATION_ATTEMPT_WINDOW_SECONDS"] = "3600"

        try:
            with patch("services.auth_limits.get_redis_client", return_value=None):
                results = []
                for i in range(4):
                    request = make_request(
                        headers=[(b"x-forwarded-for", b"203.0.113.50")],
                        client_host="127.0.0.1",
                    )
                    # Different emails each call, so only the IP cap kicks in.
                    results.append(
                        auth_limits.consume_verification_attempt_limit(
                            request, f"victim{i}@example.com"
                        )
                    )
        finally:
            os.environ.pop("VERIFICATION_ATTEMPT_PER_EMAIL_LIMIT", None)
            os.environ.pop("VERIFICATION_ATTEMPT_PER_IP_LIMIT", None)
            os.environ.pop("VERIFICATION_ATTEMPT_WINDOW_SECONDS", None)

        self.assertEqual([r[0] for r in results], [True, True, True, False])

    def test_admin_login_limit_ignores_spoofed_forwarded_for(self):
        os.environ["ADMIN_LOGIN_PER_IP_LIMIT"] = "1"
        request_a = make_request(
            headers=[(b"x-forwarded-for", b"198.51.100.211")],
            client_host="203.0.113.70",
        )
        request_b = make_request(
            headers=[(b"x-forwarded-for", b"198.51.100.212")],
            client_host="203.0.113.70",
        )

        with patch("services.auth_limits.get_redis_client", return_value=None):
            first = auth_limits.consume_admin_login_limit(request_a)
            second = auth_limits.consume_admin_login_limit(request_b)

        self.assertEqual(first, (True, None))
        self.assertFalse(second[0])
        self.assertIn("管理者ログインの試行回数が多すぎます。", second[1])


if __name__ == "__main__":
    unittest.main()
