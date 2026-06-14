import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.auth import api_send_login_code, api_verify_login_code
from blueprints.verification import api_send_verification_email, api_verify_registration_code
from tests.helpers.request_helpers import build_request


# 会員登録やログイン時のコード検証用APIテスト向けHTTPリクエストを構築します。
# Build a mock HTTP request for testing registration/login verification code APIs.
def make_request(path, json_body, session=None):
    return build_request(method="POST", path=path, json_body=json_body, session=session)


# 登録確認メールやログインコードの有効期限、試行回数上限（ブルートフォース保護）、セッションIDローテーションなどの挙動を検証するテストクラス。
# Test class to check verification/login code limits, expiration, maximum attempts, and session ID rotation.
class VerificationCodeLimitsTestCase(unittest.TestCase):
    # 新規登録メール送信時に、セッション内にコード、発行時刻(issued_at)、および初期試行回数(attempts)が記録されることを検証します。
    # Verify that sending a registration email records the generated code, issued_at timestamp, and attempts count in the session.
    def test_send_verification_email_stores_issued_at_and_attempts(self):
        session = {"_seed": True}
        request = make_request(
            "/api/send_verification_email",
            {"email": "new-user@example.com"},
            session=session,
        )

        # 各種処理をモックして登録メール送信APIを実行
        # Mock limits, user checks, code generation, and sending to run the registration email API
        with patch("blueprints.verification.consume_auth_email_send_limits", return_value=(True, None)):
            with patch("blueprints.verification.consume_auth_email_daily_quota", return_value=(True, 1, 50)):
                with patch("blueprints.verification.get_user_by_email", return_value=None):
                    with patch("blueprints.verification.create_user", return_value=10):
                        with patch("blueprints.verification.generate_verification_code", return_value="123456"):
                            with patch("blueprints.verification.time.time", return_value=1000):
                                with patch("blueprints.verification.send_email"):
                                    response = asyncio.run(api_send_verification_email(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session["verification_code"], "123456")
        self.assertEqual(session["verification_code_issued_at"], 1000)
        self.assertEqual(session["verification_code_attempts"], 0)

    # 登録確認コードの有効期限が切れた場合に、検証が拒否されセッションから認証情報がクリアされることを検証します。
    # Verify that registration verification fails if the code has expired, clearing temporary verification data from the session.
    def test_verify_registration_code_fails_when_expired_and_clears_session(self):
        session = {
            "verification_code": "111111",
            "temp_user_id": 7,
            "verification_code_issued_at": 1000,
            "verification_code_attempts": 0,
        }
        request = make_request(
            "/api/verify_registration_code",
            {"authCode": "111111"},
            session=session,
        )

        # 有効期限が切れた時間（1000秒後）をモックして検証を実行
        # Mock time elapsed beyond expiration window (1000 seconds later) to run verification
        with patch("blueprints.verification.time.time", return_value=2000):
            response = asyncio.run(api_verify_registration_code(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("有効期限", payload["error"])
        self.assertNotIn("verification_code", session)
        self.assertNotIn("verification_code_issued_at", session)
        self.assertNotIn("verification_code_attempts", session)

    # 登録確認コードの誤入力試行回数が上限に達した場合、検証がブロックされ認証情報がクリアされることを検証します。
    # Verify that registration verification is blocked after reaching the max attempt limit, clearing temporary data from the session.
    def test_verify_registration_code_blocks_when_attempt_limit_reached(self):
        session = {
            "verification_code": "111111",
            "temp_user_id": 7,
            "verification_code_issued_at": 1000,
            "verification_code_attempts": 4,
        }
        request = make_request(
            "/api/verify_registration_code",
            {"authCode": "000000"},
            session=session,
        )

        # 最大試行回数に到達した直後の検証実行
        # Run verification when the attempts count is already at the limit
        with patch("blueprints.verification.time.time", return_value=1001):
            response = asyncio.run(api_verify_registration_code(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("試行回数", payload["error"])
        self.assertNotIn("verification_code", session)
        self.assertNotIn("verification_code_issued_at", session)
        self.assertNotIn("verification_code_attempts", session)

    # ログインコード送信時に、セッション内にログインコード、発行時刻(issued_at)、および初期試行回数(attempts)が記録されることを検証します。
    # Verify that sending a login code records the generated login code, issued_at timestamp, and attempts count in the session.
    def test_send_login_code_stores_issued_at_and_attempts(self):
        session = {"_seed": True}
        request = make_request(
            "/api/send_login_code",
            {"email": "user@example.com"},
            session=session,
        )

        # ログインコード送信APIのモック実行
        # Mock necessary components and run send login code API
        with patch("blueprints.auth.consume_auth_email_send_limits", return_value=(True, None)):
            with patch(
                "blueprints.auth.get_user_by_email",
                return_value={"id": 1, "email": "user@example.com", "is_verified": True},
            ):
                with patch("blueprints.auth.consume_auth_email_daily_quota", return_value=(True, 1, 50)):
                    with patch("blueprints.auth.generate_verification_code", return_value="654321"):
                        with patch("blueprints.auth.time.time", return_value=3000):
                            with patch("blueprints.auth.send_email"):
                                response = asyncio.run(api_send_login_code(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session["login_verification_code"], "654321")
        self.assertEqual(session["login_verification_code_issued_at"], 3000)
        self.assertEqual(session["login_verification_code_attempts"], 0)

    # ログインコードの有効期限が切れた場合に、検証が拒否されセッションから認証情報がクリアされることを検証します。
    # Verify that login verification fails if the code has expired, clearing temporary login data from the session.
    def test_verify_login_code_fails_when_expired_and_clears_session(self):
        session = {
            "login_verification_code": "222222",
            "login_temp_user_id": 12,
            "login_verification_code_issued_at": 1000,
            "login_verification_code_attempts": 0,
        }
        request = make_request("/api/verify_login_code", {"authCode": "222222"}, session=session)

        # 有効期限が切れた時間（1000秒後）をモックして検証を実行
        # Mock time elapsed beyond expiration window (1000 seconds later) to run verification
        with patch("blueprints.auth.time.time", return_value=2000):
            response = asyncio.run(api_verify_login_code(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("有効期限", payload["error"])
        self.assertNotIn("login_verification_code", session)
        self.assertNotIn("login_verification_code_issued_at", session)
        self.assertNotIn("login_verification_code_attempts", session)

    # ログインコードの誤入力試行回数が上限に達した場合、検証がブロックされ認証情報がクリアされることを検証します。
    # Verify that login verification is blocked after reaching the max attempt limit, clearing temporary data from the session.
    def test_verify_login_code_blocks_when_attempt_limit_reached(self):
        session = {
            "login_verification_code": "222222",
            "login_temp_user_id": 12,
            "login_verification_code_issued_at": 1000,
            "login_verification_code_attempts": 4,
        }
        request = make_request("/api/verify_login_code", {"authCode": "000000"}, session=session)

        # 最大試行回数に到達した直後の検証実行
        # Run verification when the attempts count is already at the limit
        with patch("blueprints.auth.time.time", return_value=1001):
            response = asyncio.run(api_verify_login_code(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("試行回数", payload["error"])
        self.assertNotIn("login_verification_code", session)
        self.assertNotIn("login_verification_code_issued_at", session)
        self.assertNotIn("login_verification_code_attempts", session)

    # ログインコード検証成功時に、セッションIDがローテーションされ、セッションが永続化（permanent）されることを検証します。
    # Verify that successful login code verification rotates the session ID and sets the session as permanent.
    def test_verify_login_code_rotates_session_and_sets_permanent_on_success(self):
        session = {
            "login_verification_code": "222222",
            "login_temp_user_id": 12,
            "login_verification_code_issued_at": 1000,
            "login_verification_code_attempts": 0,
            "csrf_token": "csrf-token",
        }
        request = make_request("/api/verify_login_code", {"authCode": "222222"}, session=session)
        request.scope["session_id"] = "old-login-session"

        # ログインコード検証の成功時のDB呼び出しやタスク複製をモック
        # Mock user lookup, default tasks copy, and verify successful response
        with patch("blueprints.auth.time.time", return_value=1001):
            with patch(
                "blueprints.auth.get_user_by_id",
                return_value={"id": 12, "email": "user@example.com", "is_verified": True},
            ):
                with patch("blueprints.auth.copy_default_tasks_for_user"):
                    response = asyncio.run(api_verify_login_code(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["flow"], "login")
        self.assertFalse(payload["offer_passkey_setup"])
        self.assertEqual(session["user_id"], 12)
        self.assertEqual(session["user_email"], "user@example.com")
        self.assertTrue(session["_permanent"])
        self.assertEqual(session["csrf_token"], "csrf-token")
        self.assertIsNone(request.scope["session_id"])
        self.assertEqual(request.scope["_session_ids_to_delete"], {"old-login-session"})

    # ログインコードが正しくても対象ユーザーが存在しない場合に、エラー（401）となり認証情報が破棄されることを検証します。
    # Verify that login verification fails if the user is no longer found in the database, clearing temporary login data.
    def test_verify_login_code_fails_when_user_is_missing(self):
        session = {
            "login_verification_code": "222222",
            "login_temp_user_id": 12,
            "login_verification_code_issued_at": 1000,
            "login_verification_code_attempts": 0,
        }
        request = make_request("/api/verify_login_code", {"authCode": "222222"}, session=session)

        # ユーザーが存在しないケースをモックして検証
        # Mock missing user and verify response
        with patch("blueprints.auth.time.time", return_value=1001):
            with patch("blueprints.auth.get_user_by_id", return_value=None):
                response = asyncio.run(api_verify_login_code(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("ユーザーが存在しない", payload["error"])
        self.assertNotIn("login_verification_code", session)
        self.assertNotIn("login_temp_user_id", session)

    # ログイン処理時のデフォルトタスク複製処理でエラーが発生した場合でも、ユーザーのログイン処理自体は成功（堅牢性）と扱われることを検証します。
    # Verify that a failure in copying default tasks does not block the user from logging in successfully (resilience).
    def test_verify_login_code_keeps_success_when_copy_default_tasks_fails(self):
        session = {
            "login_verification_code": "222222",
            "login_temp_user_id": 12,
            "login_verification_code_issued_at": 1000,
            "login_verification_code_attempts": 0,
        }
        request = make_request("/api/verify_login_code", {"authCode": "222222"}, session=session)

        # デフォルトタスク複製時のRuntimeErrorをモック
        # Mock a RuntimeError during default tasks copy and verify successful login
        with patch("blueprints.auth.time.time", return_value=1001):
            with patch(
                "blueprints.auth.get_user_by_id",
                return_value={"id": 12, "email": "user@example.com", "is_verified": True},
            ):
                with patch(
                    "blueprints.auth.copy_default_tasks_for_user",
                    side_effect=RuntimeError("task copy failed"),
                ):
                    response = asyncio.run(api_verify_login_code(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["flow"], "login")
        self.assertFalse(payload["offer_passkey_setup"])
        self.assertEqual(session["user_id"], 12)

    # 登録確認コード検証成功時に、ユーザーが確認済み(is_verified)となり、セッションIDがローテーションされることを検証します。
    # Verify that successful registration code verification marks the user as verified, rotates the session ID, and sets the session as permanent.
    def test_verify_registration_code_sets_permanent_and_rotates_session(self):
        session = {
            "verification_code": "111111",
            "temp_user_id": 7,
            "verification_code_issued_at": 1000,
            "verification_code_attempts": 0,
            "csrf_token": "csrf-token",
        }
        request = make_request("/api/verify_registration_code", {"authCode": "111111"}, session=session)
        request.scope["session_id"] = "old-registration-session"

        # 登録確認コードの成功時のDB呼び出しやタスク複製をモック
        # Mock user lookup, verification update, and default tasks copy on registration success
        with patch("blueprints.verification.time.time", return_value=1001):
            with patch(
                "blueprints.verification.get_user_by_id",
                return_value={"id": 7, "email": "user@example.com", "is_verified": False},
            ):
                with patch("blueprints.verification.set_user_verified"):
                    with patch("blueprints.verification.copy_default_tasks_for_user"):
                        response = asyncio.run(api_verify_registration_code(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["flow"], "register")
        self.assertTrue(payload["offer_passkey_setup"])
        self.assertEqual(session["user_id"], 7)
        self.assertEqual(session["user_email"], "user@example.com")
        self.assertTrue(session["_permanent"])
        self.assertEqual(session["csrf_token"], "csrf-token")
        self.assertIsNone(request.scope["session_id"])
        self.assertEqual(request.scope["_session_ids_to_delete"], {"old-registration-session"})

    # 登録確認コードが正しくても対象ユーザーが存在しない場合に、エラー（401）となり認証情報が破棄されることを検証します。
    # Verify that registration verification fails if the temporary user is missing from the database.
    def test_verify_registration_code_fails_when_user_is_missing(self):
        session = {
            "verification_code": "111111",
            "temp_user_id": 7,
            "verification_code_issued_at": 1000,
            "verification_code_attempts": 0,
        }
        request = make_request("/api/verify_registration_code", {"authCode": "111111"}, session=session)

        # ユーザーが存在しないケースをモックして検証
        # Mock missing user and verify response
        with patch("blueprints.verification.time.time", return_value=1001):
            with patch("blueprints.verification.get_user_by_id", return_value=None):
                response = asyncio.run(api_verify_registration_code(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("ユーザーが存在しません", payload["error"])
        self.assertNotIn("verification_code", session)
        self.assertNotIn("temp_user_id", session)


if __name__ == "__main__":
    unittest.main()
