"""メール認証の統合フロー(ログイン/新規登録の振り分け)と、パスキーのルート(登録・認証オプション、検証、期限切れ、署名カウンタ更新失敗、レート制限)を検証する単体テスト。

Unit tests for the unified email-auth flow (routing between login and registration)
and the passkey routes (register/authenticate options, verification, expired ceremonies, sign-count update failures, rate limits).
"""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from blueprints.auth import (
    api_passkey_authenticate_options,
    api_passkey_authenticate_verify,
    api_passkey_register_options,
    api_send_email_code,
    api_verify_email_code,
)
from services.error_messages import ERROR_PASSKEY_USAGE_UPDATE_FAILED
from services.web import jsonify
from tests.helpers.request_helpers import build_request


# 日本語: POST リクエストの疑似オブジェクトを作る。
# English: Build a fake POST request.
def make_request(path: str, *, json_body=None, session=None):
    return build_request(method="POST", path=path, json_body=json_body, session=session)


# 日本語: run_blocking の代替。スレッドに逃がさず、その場で同期関数を実行する。
# English: Stand-in for run_blocking that runs the sync function in place instead of offloading it to a thread.
async def immediate_run_blocking(func, *args, **kwargs):
    return func(*args, **kwargs)


# 日本語: Unified Email Auth Flowの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Unified Email Auth Flow.
class UnifiedEmailAuthFlowTestCase(unittest.TestCase):
    # 日本語: 登録済みで検証済みのユーザーには、メールコード送信がログインフロー(api_send_login_code)に振り分けられることを検証します。
    # English: Verify that send email code uses login flow for verified user.
    def test_send_email_code_uses_login_flow_for_verified_user(self):
        request = make_request(
            "/api/auth/send_email_code",
            json_body={"email": "user@example.com"},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.auth.get_user_by_email", return_value={"id": 1, "is_verified": True}):
            with patch(
                "blueprints.auth.api_send_login_code",
                new=AsyncMock(return_value=jsonify({"status": "success"})),
            ) as mock_login:
                response = asyncio.run(api_send_email_code(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_login.await_count, 1)

    # 日本語: 未登録のユーザーには、メールコード送信が新規登録フロー(確認メール送信)に振り分けられることを検証します。
    # English: Verify that send email code uses registration flow for unknown user.
    def test_send_email_code_uses_registration_flow_for_unknown_user(self):
        request = make_request(
            "/api/auth/send_email_code",
            json_body={"email": "new-user@example.com"},
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.auth.get_user_by_email", return_value=None):
            with patch(
                "blueprints.auth.api_send_verification_email",
                new=AsyncMock(return_value=jsonify({"status": "success"})),
            ) as mock_register:
                response = asyncio.run(api_send_email_code(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_register.await_count, 1)

    # 日本語: セッションにログイン中のコード検証状態があるとき、コード検証がログイン用の検証に振り分けられることを検証します。
    # English: Verify that verify email code uses login verification when login session exists.
    def test_verify_email_code_uses_login_verification_when_login_session_exists(self):
        request = make_request(
            "/api/auth/verify_email_code",
            json_body={"authCode": "123456"},
            session={
                "login_verification_code": "123456",
                "login_temp_user_id": 10,
            },
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch(
            "blueprints.auth.api_verify_login_code",
            new=AsyncMock(return_value=jsonify({"status": "success"})),
        ) as mock_verify:
            response = asyncio.run(api_verify_email_code(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_verify.await_count, 1)

    # 日本語: セッションに新規登録中のコード検証状態があるとき、コード検証が新規登録用の検証に振り分けられることを検証します。
    # English: Verify that verify email code uses registration verification when registration session exists.
    def test_verify_email_code_uses_registration_verification_when_registration_session_exists(self):
        request = make_request(
            "/api/auth/verify_email_code",
            json_body={"authCode": "123456"},
            session={
                "verification_code": "123456",
                "temp_user_id": 10,
            },
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch(
            "blueprints.auth.api_verify_registration_code",
            new=AsyncMock(return_value=jsonify({"status": "success"})),
        ) as mock_verify:
            response = asyncio.run(api_verify_email_code(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_verify.await_count, 1)


# 日本語: Passkey Routeの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Passkey Route.
class PasskeyRouteTestCase(unittest.TestCase):
    # 日本語: レート制限を超えたとき、パスキー認証オプション取得 API が 429 を返すことを検証します。
    # English: Verify that passkey authenticate options returns 429 when rate limited.
    def test_passkey_authenticate_options_returns_429_when_rate_limited(self):
        request = make_request("/api/passkeys/authenticate/options", session={})

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch(
            "blueprints.auth.consume_passkey_auth_options_limit",
            return_value=(False, "too many attempts"),
        ):
            response = asyncio.run(api_passkey_authenticate_options(request))

        payload = json.loads(response.body.decode())
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), "60")
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "too many attempts")

    # 日本語: パスキー登録オプション取得 API がログインを要求することを検証します。
    # English: Verify that passkey register options requires login.
    def test_passkey_register_options_requires_login(self):
        request = make_request("/api/passkeys/register/options", session={})
        response = asyncio.run(api_passkey_register_options(request))
        self.assertEqual(response.status_code, 401)

    # 日本語: パスキー登録オプション取得 API が、発行した challenge をセッションに保存することを検証します。
    # English: Verify that passkey register options stores challenge.
    def test_passkey_register_options_stores_challenge(self):
        session = {"user_id": 7}
        request = make_request("/api/passkeys/register/options", session=session)
        options = SimpleNamespace(challenge=b"raw-challenge")

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch(
            "blueprints.auth.get_user_by_id",
            return_value={"id": 7, "email": "user@example.com", "username": "User"},
        ):
            with patch("blueprints.auth.list_passkeys_for_user", return_value=[]):
                with patch("blueprints.auth.generate_registration_options", return_value=options):
                    with patch(
                        "blueprints.auth.options_to_json",
                        return_value=json.dumps(
                            {
                                "rp": {"name": "Chat Core", "id": "localhost"},
                                "user": {"name": "user@example.com", "displayName": "User", "id": "abc"},
                                "challenge": "challenge-token",
                            }
                        ),
                    ):
                        with patch("blueprints.auth.bytes_to_base64url", return_value="challenge-token"):
                            with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                                response = asyncio.run(api_passkey_register_options(request))

        payload = json.loads(response.body.decode())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(session["passkey_registration"]["challenge"], "challenge-token")
        self.assertIn("issued_at", session["passkey_registration"])
        self.assertIn("ceremony_id", session["passkey_registration"])
        self.assertEqual(payload["challenge"], "challenge-token")

    # 日本語: パスキー認証の検証に成功すると、対象ユーザーのログイン状態が記録されることを検証します。
    # English: Verify that passkey authentication verify logs user in.
    def test_passkey_authentication_verify_logs_user_in(self):
        session = {
            "passkey_authentication": {
                "challenge": "challenge-token",
                "issued_at": 1000,
                "ceremony_id": "ceremony-1",
            }
        }
        request = make_request(
            "/api/passkeys/authenticate/verify",
            json_body={"credential": {"id": "cred-1", "rawId": "cred-raw-1", "response": {}}},
            session=session,
        )
        verified = SimpleNamespace(
            new_sign_count=11,
            credential_backed_up=False,
            credential_device_type=SimpleNamespace(value="single_device"),
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch(
            "blueprints.auth.get_passkey_by_credential_id",
            return_value={
                "id": 4,
                "user_id": 7,
                "public_key": "public-key",
                "sign_count": 5,
            },
        ) as mock_get_passkey:
            with patch("blueprints.auth.base64url_to_bytes", side_effect=lambda value: str(value).encode("utf-8")):
                with patch("blueprints.auth.verify_authentication_response", return_value=verified):
                    with patch(
                        "blueprints.auth.get_user_by_id",
                        return_value={"id": 7, "email": "user@example.com", "is_verified": True},
                    ):
                        with patch("blueprints.auth.consume_passkey_auth_verify_limit", return_value=(True, None)):
                            with patch("blueprints.auth.update_passkey_usage"):
                                with patch("blueprints.auth.copy_default_tasks_for_user"):
                                    with patch("blueprints.auth.time.time", return_value=1001):
                                        with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                                            response = asyncio.run(api_passkey_authenticate_verify(request))

        payload = json.loads(response.body.decode())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(session["user_id"], 7)
        self.assertEqual(session["user_email"], "user@example.com")
        mock_get_passkey.assert_called_once_with("cred-raw-1")
        self.assertNotIn("passkey_authentication", session)

    # 日本語: パスキー認証の検証が、期限切れの認証セレモニー(challenge)を拒否することを検証します。
    # English: Verify that passkey authentication verify rejects expired ceremony.
    def test_passkey_authentication_verify_rejects_expired_ceremony(self):
        session = {
            "passkey_authentication": {
                "challenge": "challenge-token",
                "issued_at": 1000,
                "ceremony_id": "ceremony-1",
            }
        }
        request = make_request(
            "/api/passkeys/authenticate/verify",
            json_body={"credential": {"id": "cred-1", "rawId": "cred-1", "response": {}}},
            session=session,
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.auth.consume_passkey_auth_verify_limit", return_value=(True, None)):
            with patch("blueprints.auth.time.time", return_value=1400):
                response = asyncio.run(api_passkey_authenticate_verify(request))

        payload = json.loads(response.body.decode())
        self.assertEqual(response.status_code, 400)
        self.assertIn("有効期限", payload["error"])
        self.assertNotIn("passkey_authentication", session)

    # 日本語: 署名カウンタの保存に失敗した場合、ログインさせずに500を返すことを検証します。
    # English: Verify that a failed sign count update aborts the login and returns HTTP 500.
    def test_passkey_authentication_verify_rejects_login_when_usage_update_fails(self):
        session = {
            "passkey_authentication": {
                "challenge": "challenge-token",
                "issued_at": 1000,
                "ceremony_id": "ceremony-1",
            }
        }
        request = make_request(
            "/api/passkeys/authenticate/verify",
            json_body={"credential": {"id": "cred-1", "rawId": "cred-1", "response": {}}},
            session=session,
        )
        verified = SimpleNamespace(
            new_sign_count=11,
            credential_backed_up=False,
            credential_device_type=SimpleNamespace(value="single_device"),
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch(
            "blueprints.auth.get_passkey_by_credential_id",
            return_value={
                "id": 4,
                "user_id": 7,
                "public_key": "public-key",
                "sign_count": 5,
            },
        ):
            with patch("blueprints.auth.base64url_to_bytes", side_effect=lambda value: str(value).encode("utf-8")):
                with patch("blueprints.auth.verify_authentication_response", return_value=verified):
                    with patch(
                        "blueprints.auth.get_user_by_id",
                        return_value={"id": 7, "email": "user@example.com", "is_verified": True},
                    ):
                        with patch("blueprints.auth.consume_passkey_auth_verify_limit", return_value=(True, None)):
                            with patch("blueprints.auth.update_passkey_usage", side_effect=RuntimeError("db error")):
                                with patch("blueprints.auth.copy_default_tasks_for_user"):
                                    with patch("blueprints.auth.time.time", return_value=1001):
                                        with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                                            response = asyncio.run(api_passkey_authenticate_verify(request))

        payload = json.loads(response.body.decode())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], ERROR_PASSKEY_USAGE_UPDATE_FAILED)
        self.assertNotIn("user_id", session)
        self.assertNotIn("passkey_authentication", session)

    # 日本語: レート制限を超えたとき、パスキー認証の検証 API が 429 を返すことを検証します。
    # English: Verify that passkey authentication verify returns 429 when rate limited.
    def test_passkey_authentication_verify_returns_429_when_rate_limited(self):
        session = {
            "passkey_authentication": {
                "challenge": "challenge-token",
                "issued_at": 1000,
                "ceremony_id": "ceremony-1",
            }
        }
        request = make_request(
            "/api/passkeys/authenticate/verify",
            json_body={"credential": {"id": "cred-1", "rawId": "cred-1", "response": {}}},
            session=session,
        )

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch(
            "blueprints.auth.consume_passkey_auth_verify_limit",
            return_value=(False, "too many attempts"),
        ):
            response = asyncio.run(api_passkey_authenticate_verify(request))

        payload = json.loads(response.body.decode())
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), "60")
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "too many attempts")


if __name__ == "__main__":
    unittest.main()
