"""メールログイン成功時に、同じブラウザのゲスト投稿プロンプトがログインユーザーへ引き継がれることを検証するテスト。

Tests that a successful email login claims this browser's guest prompts for the logged-in user.
"""

import asyncio
import unittest
from unittest.mock import patch

from blueprints.auth import api_verify_login_code
from tests.helpers.request_helpers import build_request


# run_blocking を差し替え、スレッドへ逃がさずその場で同期関数を実行する。
# Replaces run_blocking so the sync function runs inline instead of in a worker thread.
async def immediate_run_blocking(func, *args, **kwargs):
    return func(*args, **kwargs)


# api_verify_login_code が認証後のゲスト投稿の引き継ぎ（claim）を呼ぶことを確かめる。
# Checks that api_verify_login_code triggers the guest prompt claim after authentication.
class GuestPromptAuthClaimTestCase(unittest.TestCase):
    def test_email_login_claims_this_browser_guest_prompt_after_session_rotation(self):
        guest_token = "guest-token-which-is-long-enough-to-be-valid"
        request = build_request(
            method="POST",
            path="/api/verify_login_code",
            json_body={"authCode": "123456"},
            session={
                "login_verification_code": "123456",
                "login_temp_user_id": 12,
                "login_verification_code_issued_at": 1000,
                "login_verification_code_attempts": 0,
                "guest_prompt_token": guest_token,
            },
        )

        with patch("blueprints.auth.time.time", return_value=1001):
            with patch(
                "blueprints.auth.get_user_by_id",
                return_value={"id": 12, "email": "user@example.com", "is_verified": True},
            ):
                with patch("blueprints.auth.copy_default_tasks_for_user"):
                    with patch(
                        "blueprints.auth.claim_guest_prompts_for_user",
                        return_value=[77],
                    ) as claim:
                        with patch("blueprints.auth.run_blocking", new=immediate_run_blocking):
                            response = asyncio.run(api_verify_login_code(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.session["user_id"], 12)
        self.assertEqual(request.session["guest_prompt_token"], guest_token)
        claim.assert_called_once_with(12, guest_token)


if __name__ == "__main__":
    unittest.main()
