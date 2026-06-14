import asyncio
import json
import unittest
from unittest.mock import Mock, patch

from blueprints.auth import api_send_login_code
from blueprints.prompt_share.prompt_manage_api import get_my_prompts
from services.web import DEFAULT_INTERNAL_ERROR_MESSAGE, log_and_internal_server_error
from tests.helpers.request_helpers import build_request


# 日本語: テスト用のHTTPリクエストを構築するヘルパー関数。
# English: Helper function to build an HTTP request for testing.
def make_request(
    *,
    method: str,
    path: str,
    session=None,
    json_body=None,
):
    return build_request(
        method=method,
        path=path,
        session=session,
        json_body=json_body or {},
    )


# 日本語: エラーハンドリング機能（内部エラーのマスク処理・ログ記録）をテストするクラス。
# English: Test class for error handling functionality (masking internal errors and logging).
class ErrorHandlingTestCase(unittest.TestCase):
    # 日本語: log_and_internal_server_error が汎用エラーペイロードを返し、ロガーでexceptionをログすることを検証します。
    # English: Verify that log_and_internal_server_error returns a generic error payload and logs the exception.
    def test_log_and_internal_server_error_returns_generic_payload_and_logs(self):
        mock_logger = Mock()

        response = log_and_internal_server_error(
            mock_logger,
            "operation failed",
            status="fail",
        )

        # 日本語: 500ステータスで汎用エラーメッセージが返り、ロガーが呼ばれていることを確認
        # English: Confirm 500 status, generic error message, and logger called once
        self.assertEqual(response.status_code, 500)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], DEFAULT_INTERNAL_ERROR_MESSAGE)
        mock_logger.exception.assert_called_once_with("operation failed")

    # 日本語: ログインコード送信処理でメール送信が失敗した場合に、内部のエラー詳細がレスポンスに漏れないことを検証します。
    # English: Verify that internal exception details are not leaked in the response when email sending fails during login code dispatch.
    def test_send_login_code_does_not_leak_internal_exception_message(self):
        request = make_request(
            method="POST",
            path="/api/send_login_code",
            json_body={"email": "user@example.com"},
        )

        # 日本語: ユーザー取得・メールクォータを正常に通過させ、メール送信のみを失敗させる
        # English: Pass user lookup and email quota, but fail the actual email sending
        with patch(
            "blueprints.auth.get_user_by_email",
            return_value={"id": 1, "email": "user@example.com", "is_verified": True},
        ):
            with patch(
                "blueprints.auth.consume_auth_email_daily_quota",
                return_value=(True, 49, 50),
            ):
                with patch(
                    "blueprints.auth.send_email",
                    side_effect=RuntimeError("smtp auth failed"),
                ):
                    with patch("blueprints.auth.logger.exception") as mock_log:
                        response = asyncio.run(api_send_login_code(request))

        # 日本語: 500エラーが返り、SMTP詳細がペイロードに含まれないことを確認
        # English: Confirm 500 error response and SMTP details are not in the payload
        self.assertEqual(response.status_code, 500)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], DEFAULT_INTERNAL_ERROR_MESSAGE)
        self.assertNotIn("smtp auth failed", payload["error"])
        mock_log.assert_called_once()

    # 日本語: プロンプト管理APIでDB接続エラーが発生した場合に、エラーの詳細がレスポンスに漏れないことを検証します。
    # English: Verify that internal DB error details are not leaked in the response when the prompt manage API fails.
    def test_prompt_manage_does_not_leak_internal_exception_message(self):
        request = make_request(
            method="GET",
            path="/prompt_manage/api/my_prompts",
            session={"user_id": 1},
        )

        # 日本語: run_blocking を失敗させ、ログが記録されることを確認
        # English: Make run_blocking fail and confirm that the error is logged
        with patch(
            "blueprints.prompt_share.prompt_manage_api.run_blocking",
            side_effect=RuntimeError("sensitive-db-error"),
        ):
            with patch(
                "blueprints.prompt_share.prompt_manage_api.logger.exception"
            ) as mock_log:
                response = asyncio.run(get_my_prompts(request))

        # 日本語: 500エラーが返り、センシティブなDB詳細が含まれないことを確認
        # English: Confirm 500 error response and sensitive DB details are not included
        self.assertEqual(response.status_code, 500)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], DEFAULT_INTERNAL_ERROR_MESSAGE)
        self.assertNotIn("sensitive-db-error", payload["error"])
        mock_log.assert_called_once()


if __name__ == "__main__":
    unittest.main()
