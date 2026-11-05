"""メール送信サービス（services.email_service）の、認証メールの文面と HTML、
リクエストからのロケール判定、Resend の設定と送信を検証するテスト。

Tests services.email_service: verification email text and HTML, locale detection from the request, and
Resend configuration and sending.
"""

import unittest
from unittest.mock import patch

from starlette.requests import Request

from services import email_service


# 日本語: Resend への HTTP 呼び出しの応答を模した、テスト用のダミー応答です。
# English: Mock Fake Response class for testing.
class FakeResponse:
    def __init__(self, status_code=200, json_payload=None, text=""):
        self.status_code = status_code
        self._json_payload = json_payload
        self.text = text

    def json(self):
        # 日本語: 条件に基づいて処理の流れを切り替えます。
        # English: Switch the execution flow based on the condition.
        if isinstance(self._json_payload, Exception):
            raise self._json_payload
        return self._json_payload


# 日本語: 認証メールの文面・HTML・ロケール判定と、Resend の設定読み込み・送信処理を検証する。
# English: Test case class to verify the functionality and specifications of Email Service Config.
class EmailServiceConfigTestCase(unittest.TestCase):
    def test_render_english_verification_email_uses_typed_template(self):
        subject, body = email_service.render_verification_email(
            "login_verification",
            code="654321",
            locale="en-US",
        )

        self.assertEqual(subject, "Chat-Core AI: Sign-in verification code")
        self.assertIn("Verification code: 654321", body)
        html = email_service._build_email_html(
            subject,
            body,
            template_kind="login_verification",
            code="654321",
            locale="en",
        )
        self.assertIn('<html lang="en">', html)
        self.assertIn("Sign-in verification code", html)

    def test_request_email_locale_uses_canonical_accept_language_parser(self):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/",
                "headers": [(b"accept-language", b"fr;q=1, en-US;q=0.8, ja;q=0.5")],
                "session": {},
            }
        )

        self.assertEqual(email_service.resolve_request_email_locale(request), "en")
    # 日本語: Resend 設定の読み込みが、設定された送信元アドレスを使うことを検証します。
    # English: Verify that load resend config uses resend from address.
    def test_load_resend_config_uses_resend_from_address(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "re_test",
                "RESEND_FROM_ADDRESS": "Chat Core <noreply@example.com>",
            },
            clear=True,
        ):
            api_key, from_address = email_service._load_resend_config()

        self.assertEqual(api_key, "re_test")
        self.assertEqual(from_address, "Chat Core <noreply@example.com>")

    # 日本語: Resend 設定の読み込みが、送信元アドレスを必須とすることを検証します。
    # English: Verify that load resend config requires resend from address.
    def test_load_resend_config_requires_resend_from_address(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "re_test",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                email_service._load_resend_config()

    # 日本語: Resend 設定が欠けているとき、読み込みが例外を送出することを検証します。
    # English: Verify that load resend config raises when missing.
    def test_load_resend_config_raises_when_missing(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                email_service._load_resend_config()

    # 日本語: メール送信が、HTML 本文とプレーンテキスト本文の両方を Resend へ POST することを検証します。
    # English: Verify that send email posts rich html and plain text message to resend.
    def test_send_email_posts_rich_html_and_plain_text_message_to_resend(self):
        fake_response = FakeResponse(status_code=200, json_payload={"id": "email-id"})
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "re_test",
                "RESEND_FROM_ADDRESS": "Chat Core <noreply@example.com>",
            },
            clear=True,
        ):
            with patch(
                "services.email_service.http_client.post",
                return_value=fake_response,
            ) as mock_post:
                email_service.send_email(
                    to_address="receiver@example.com",
                    subject="AIチャットサービス: ログイン認証コード",
                    body_text="以下の認証コードをログイン画面に入力してください。\n\n認証コード: 123456",
                )

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer re_test")
        self.assertEqual(kwargs["timeout"], 10)
        payload = kwargs["json"]
        self.assertEqual(payload["from"], "Chat Core <noreply@example.com>")
        self.assertEqual(payload["to"], ["receiver@example.com"])
        self.assertEqual(payload["subject"], "AIチャットサービス: ログイン認証コード")
        self.assertEqual(
            payload["text"],
            "以下の認証コードをログイン画面に入力してください。\n\n認証コード: 123456",
        )
        self.assertIn("Chat-Core AI", payload["html"])
        self.assertIn("ログイン認証コード", payload["html"])
        self.assertIn("123456", payload["html"])
        self.assertIn("Verification code", payload["html"])

    # 日本語: HTML メールの組み立てが、本文のテキストをエスケープすることを検証します。
    # English: Verify that build email html escapes text content.
    def test_build_email_html_escapes_text_content(self):
        html = email_service._build_email_html(
            "Subject <unsafe>",
            "以下の認証コードを入力してください。\n\n認証コード: 123456\n\n<script>alert(1)</script>",
        )

        self.assertIn("Subject &lt;unsafe&gt;", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    # 日本語: 設定が欠けているとき、メール送信が Resend を呼び出さないことを検証します。
    # English: Verify that send email does not call resend when config is missing.
    def test_send_email_does_not_call_resend_when_config_is_missing(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict("os.environ", {}, clear=True):
            with patch("services.email_service.http_client.post") as mock_post:
                with self.assertRaises(RuntimeError):
                    email_service.send_email(
                        to_address="receiver@example.com",
                        subject="subject",
                        body_text="body",
                    )

        mock_post.assert_not_called()

    # 日本語: Resend がエラーメッセージを返したとき、メール送信が例外を送出することを検証します。
    # English: Verify that send email raises for resend error message.
    def test_send_email_raises_for_resend_error_message(self):
        fake_response = FakeResponse(
            status_code=403,
            json_payload={"message": "invalid api key"},
        )
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "re_test",
                "RESEND_FROM_ADDRESS": "sender@example.com",
            },
            clear=True,
        ):
            with patch(
                "services.email_service.http_client.post",
                return_value=fake_response,
            ):
                with self.assertRaisesRegex(RuntimeError, "403: invalid api key"):
                    email_service.send_email(
                        to_address="receiver@example.com",
                        subject="subject",
                        body_text="body",
                    )

    # 日本語: Resend が JSON ではなくプレーンテキストのエラーを返したとき、メール送信が例外を送出することを検証します。
    # English: Verify that send email raises for resend plain text error.
    def test_send_email_raises_for_resend_plain_text_error(self):
        fake_response = FakeResponse(
            status_code=500,
            json_payload=ValueError("not json"),
            text="upstream failed",
        )
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "re_test",
                "RESEND_FROM_ADDRESS": "sender@example.com",
            },
            clear=True,
        ):
            with patch(
                "services.email_service.http_client.post",
                return_value=fake_response,
            ):
                with self.assertRaisesRegex(RuntimeError, "500: upstream failed"):
                    email_service.send_email(
                        to_address="receiver@example.com",
                        subject="subject",
                        body_text="body",
                    )


if __name__ == "__main__":
    unittest.main()
