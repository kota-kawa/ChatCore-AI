import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.auth import api_send_login_code
from blueprints.verification import api_send_verification_email
from tests.helpers.request_helpers import build_request


# 日本語: テスト用のHTTP POSTリクエストを構築します。
# English: Build a mock HTTP POST request for testing.
def make_request(path, json_body, session=None):
    return build_request(
        method="POST",
        path=path,
        json_body=json_body,
        session=session,
    )


# 日本語: メール送信制限（短時間制限・日次制限）に関するエンドポイントの振る舞いをテストするクラス。
# English: Test class to verify endpoints handling email sending limits (per-email and daily limits).
class AuthEmailLimitRoutesTestCase(unittest.TestCase):
    # 日本語: 短時間でのメール送信制限を超えた場合に、ログインコード送信APIが429ステータスを返すことを検証します。
    # English: Verify that the login code sending API returns a 429 status when the short-term per-email sending limit is exceeded.
    def test_send_login_code_returns_429_when_per_email_limit_exceeded(self):
        request = make_request("/api/send_login_code", {"email": "user@example.com"})

        # 日本語: 送信制限エラーをモックし、メール送信処理が呼ばれないことを確認
        # English: Mock limit exhaustion and verify that the send email function is not called
        with patch(
            "blueprints.auth.consume_auth_email_send_limits",
            return_value=(False, "too many attempts"),
        ):
            with patch("blueprints.auth.send_email") as mock_send_email:
                response = asyncio.run(api_send_login_code(request))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), "60")
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "too many attempts")
        mock_send_email.assert_not_called()

    # 日本語: 1日のメール送信制限を超えた場合に、ログインコード送信APIが429ステータスを返すことを検証します。
    # English: Verify that the login code sending API returns a 429 status when the daily email sending limit is exceeded.
    def test_send_login_code_returns_429_when_daily_limit_exceeded(self):
        request = make_request("/api/send_login_code", {"email": "user@example.com"})

        # 日本語: 短時間制限はパスし、日次制限およびユーザー取得などをモック
        # English: Pass the per-email limit, but mock daily quota limit and user lookup
        with patch(
            "blueprints.auth.consume_auth_email_send_limits",
            return_value=(True, None),
        ):
            with patch(
                "blueprints.auth.get_user_by_email",
                return_value={"id": 1, "email": "user@example.com", "is_verified": True},
            ):
                with patch(
                    "blueprints.auth.consume_auth_email_daily_quota",
                    return_value=(False, 0, 50),
                ):
                    with patch("blueprints.auth.send_email") as mock_send_email:
                        response = asyncio.run(api_send_login_code(request))

        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.headers.get("Retry-After"))
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["status"], "fail")
        self.assertIn("上限", payload["error"])
        mock_send_email.assert_not_called()

    # 日本語: 短時間でのメール送信制限を超えた場合に、確認メール送信APIが429ステータスを返すことを検証します。
    # English: Verify that the verification email sending API returns a 429 status when the short-term per-email sending limit is exceeded.
    def test_send_verification_email_returns_429_when_per_email_limit_exceeded(self):
        request = make_request("/api/send_verification_email", {"email": "new-user@example.com"})

        # 日本語: 送信制限エラーをモックし、メール送信処理が呼ばれないことを確認
        # English: Mock limit exhaustion and verify that the send email function is not called
        with patch(
            "blueprints.verification.consume_auth_email_send_limits",
            return_value=(False, "too many attempts"),
        ):
            with patch("blueprints.verification.send_email") as mock_send_email:
                response = asyncio.run(api_send_verification_email(request))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), "60")
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "too many attempts")
        mock_send_email.assert_not_called()

    # 日本語: 1日のメール送信制限を超えた場合に、確認メール送信APIが429ステータスを返すことを検証します。
    # English: Verify that the verification email sending API returns a 429 status when the daily email sending limit is exceeded.
    def test_send_verification_email_returns_429_when_daily_limit_exceeded(self):
        request = make_request("/api/send_verification_email", {"email": "new-user@example.com"})

        # 日本語: 短時間制限はパスし、日次制限制限エラーをモック
        # English: Pass the per-email limit, but mock daily quota limit exhaustion
        with patch(
            "blueprints.verification.consume_auth_email_send_limits",
            return_value=(True, None),
        ):
            with patch(
                "blueprints.verification.consume_auth_email_daily_quota",
                return_value=(False, 0, 50),
            ):
                with patch("blueprints.verification.send_email") as mock_send_email:
                    response = asyncio.run(api_send_verification_email(request))

        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.headers.get("Retry-After"))
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["status"], "fail")
        self.assertIn("上限", payload["error"])
        mock_send_email.assert_not_called()


if __name__ == "__main__":
    unittest.main()
