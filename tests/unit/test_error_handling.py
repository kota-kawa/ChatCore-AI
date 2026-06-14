import asyncio
import json
import unittest
from unittest.mock import Mock, patch

from blueprints.auth import api_send_login_code
from blueprints.prompt_share.prompt_manage_api import get_my_prompts
from services.web import DEFAULT_INTERNAL_ERROR_MESSAGE, log_and_internal_server_error
from tests.helpers.request_helpers import build_request


# 日本語: make request の生成処理を担当します。
# English: Handle creating for make request.
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


# 日本語: ErrorHandlingTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ErrorHandlingTestCase.
class ErrorHandlingTestCase(unittest.TestCase):
    # 日本語: test log and internal server error returns generic payload and logs のテスト検証を担当します。
    # English: Handle verifying test behavior for test log and internal server error returns generic payload and logs.
    def test_log_and_internal_server_error_returns_generic_payload_and_logs(self):
        mock_logger = Mock()

        response = log_and_internal_server_error(
            mock_logger,
            "operation failed",
            status="fail",
        )

        self.assertEqual(response.status_code, 500)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], DEFAULT_INTERNAL_ERROR_MESSAGE)
        mock_logger.exception.assert_called_once_with("operation failed")

    # 日本語: test send login code does not leak internal exception message のテスト検証を担当します。
    # English: Handle verifying test behavior for test send login code does not leak internal exception message.
    def test_send_login_code_does_not_leak_internal_exception_message(self):
        request = make_request(
            method="POST",
            path="/api/send_login_code",
            json_body={"email": "user@example.com"},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

        self.assertEqual(response.status_code, 500)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], DEFAULT_INTERNAL_ERROR_MESSAGE)
        self.assertNotIn("smtp auth failed", payload["error"])
        mock_log.assert_called_once()

    # 日本語: test prompt manage does not leak internal exception message のテスト検証を担当します。
    # English: Handle verifying test behavior for test prompt manage does not leak internal exception message.
    def test_prompt_manage_does_not_leak_internal_exception_message(self):
        request = make_request(
            method="GET",
            path="/prompt_manage/api/my_prompts",
            session={"user_id": 1},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "blueprints.prompt_share.prompt_manage_api.run_blocking",
            side_effect=RuntimeError("sensitive-db-error"),
        ):
            with patch(
                "blueprints.prompt_share.prompt_manage_api.logger.exception"
            ) as mock_log:
                response = asyncio.run(get_my_prompts(request))

        self.assertEqual(response.status_code, 500)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], DEFAULT_INTERNAL_ERROR_MESSAGE)
        self.assertNotIn("sensitive-db-error", payload["error"])
        mock_log.assert_called_once()


if __name__ == "__main__":
    unittest.main()
