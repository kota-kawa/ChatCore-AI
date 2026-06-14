import os
import unittest
from unittest.mock import patch

from services import auth_limits
from tests.helpers.request_helpers import build_request


# レートリミット検証用のHTTPリクエストを構築します。
# Build a mock HTTP request for rate limit validation.
def make_request(*, headers=None, client_host="testclient"):
    request = build_request(
        method="POST",
        path="/api/chat",
        session={},
        headers=headers or [],
    )
    request.scope["client"] = (client_host, 50000)
    return request


# ゲストユーザーによるチャット利用制限や、管理者ログインのIP制限、プロキシによるIP偽装防止などをテストするクラス。
# Test class to check guest chat daily limits, admin login IP limits, and proxy IP spoofing prevention.
class GuestChatLimitTestCase(unittest.TestCase):
    # テスト開始前に必要な環境変数のバックアップと初期設定、インメモリのレートリミット状態のクリアを行います。
    # Back up environment variables, set mock values, and clear the in-memory rate limit state before each test.
    def setUp(self):
        self.original_guest_limit = os.environ.get("GUEST_CHAT_DAILY_LIMIT")
        self.original_trusted_proxies = os.environ.get("TRUSTED_PROXY_IPS")
        self.original_admin_login_limit = os.environ.get("ADMIN_LOGIN_PER_IP_LIMIT")
        os.environ["TRUSTED_PROXY_IPS"] = "127.0.0.1,::1"
        auth_limits.clear_in_memory_rate_limit_state()

    # テスト終了後に環境変数を元の状態に復元し、インメモリのレートリミット状態をクリアします。
    # Restore original environment variables and clear the in-memory rate limit state after each test.
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

    # ゲストチャット制限回数に到達した後、追加 of チャット要求が拒否されることを検証します。
    # Verify that additional chat requests are blocked once the guest chat limit cap is reached.
    def test_guest_chat_limit_blocks_after_reaching_cap(self):
        os.environ["GUEST_CHAT_DAILY_LIMIT"] = "2"
        request = make_request(
            headers=[(b"x-forwarded-for", b"198.51.100.10")],
            client_host="127.0.0.1",
        )

        # Redisが接続できない(None)場合のインメモリ処理での挙動を検証
        # Mock Redis client as None to check the fallback in-memory state rate limiting
        with patch("services.auth_limits.get_redis_client", return_value=None):
            first = auth_limits.consume_guest_chat_daily_limit(request)
            second = auth_limits.consume_guest_chat_daily_limit(request)
            third = auth_limits.consume_guest_chat_daily_limit(request)

        self.assertEqual(first, (True, None))
        self.assertEqual(second, (True, None))
        self.assertEqual(third, (False, "1日2回までです"))

    # 環境変数の制限値設定が無効な形式のとき、デフォルトの制限回数が適用されることを検証します。
    # Verify that default limit values are applied if the environment variable value is invalid.
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

    # X-Forwarded-Forヘッダー内の送信元IPがクライアントの識別子として正しく用いられることを検証します。
    # Verify that the client IP from the X-Forwarded-For header is correctly used as the rate limit identifier.
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

    # 信頼されていない中間プロキシ/クライアントからのX-Forwarded-Forヘッダー情報が無視され、直接の接続元IPでレート制限されることを検証します。
    # Verify that X-Forwarded-For headers from untrusted clients are ignored, using the connection IP instead.
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

    # X-Forwarded-Forに複数プロキシが連なっている場合、最右端の信頼されていないIPがレート制限の識別子として用いられることを検証します。
    # Verify that the rightmost untrusted IP in X-Forwarded-For chain is used as the rate limit identifier.
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

    # 同一のメールアドレスに対する確認コード試行において、IPが変化してもメールアドレス単位の試行上限でブロックされることを検証します。
    # Verify that verification attempts are blocked after the per-email limit cap is reached, even when IPs are rotated.
    def test_verification_attempt_limit_blocks_after_per_email_cap(self):
        # 異なるIPからの同一アドレス宛のブルートフォース試行制限
        # Cross-session brute-force: same email submitted from rotating IPs still hits the per-email cap.
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

    # 同一のIPアドレスからの確認コード試行において、異なるメールアドレスを指定してもIP単位の試行上限でブロックされることを検証します。
    # Verify that verification attempts are blocked after the per-IP limit cap is reached, even when different emails are used.
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
                    # 呼び出しごとに異なる電子メール、IP制限チェックのみ発動
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

    # 管理者ログインのIP制限において、信頼されていないクライアントから送信された偽装X-Forwarded-Forヘッダーが無視されることを検証します。
    # Verify that spoofed X-Forwarded-For headers from untrusted client hosts are ignored during admin login rate limiting.
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
