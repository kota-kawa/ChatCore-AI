import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.auth import api_current_user, api_delete_user_account
from services.users import ACCOUNT_DELETE_CONFIRMATION_TEXT
from tests.helpers.request_helpers import build_request


# 日本語: make request の生成処理を担当します。
# English: Handle creating for make request.
def make_request(session=None):
    return build_request(method="GET", path="/api/current_user", session=session)


# 日本語: CurrentUserTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to CurrentUserTestCase.
class CurrentUserTestCase(unittest.TestCase):
    # 日本語: test current user logged out のテスト検証を担当します。
    # English: Handle verifying test behavior for test current user logged out.
    def test_current_user_logged_out(self):
        request = make_request()
        response = asyncio.run(api_current_user(request))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body.decode()), {"logged_in": False})

    # 日本語: test current user logged in のテスト検証を担当します。
    # English: Handle verifying test behavior for test current user logged in.
    def test_current_user_logged_in(self):
        request = make_request(session={"user_id": 7})
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.get_user_by_id") as mock_get_user:
            mock_get_user.return_value = {
                "id": 7,
                "email": "user@example.com",
                "username": "kota",
            }
            response = asyncio.run(api_current_user(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.body.decode()),
            {
                "logged_in": True,
                "user": {"id": 7, "email": "user@example.com", "username": "kota"},
            },
        )

    # 日本語: test delete user account requires login のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete user account requires login.
    def test_delete_user_account_requires_login(self):
        request = build_request(
            method="DELETE",
            path="/api/user/account",
            json_body={"confirmation": ACCOUNT_DELETE_CONFIRMATION_TEXT},
        )

        response = asyncio.run(api_delete_user_account(request))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(json.loads(response.body.decode()), {"error": "ログインが必要です。"})

    # 日本語: test delete user account rejects missing confirmation のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete user account rejects missing confirmation.
    def test_delete_user_account_rejects_missing_confirmation(self):
        request = build_request(
            method="DELETE",
            path="/api/user/account",
            session={"user_id": 7},
            json_body={"confirmation": "delete"},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.delete_user_account") as mock_delete:
            response = asyncio.run(api_delete_user_account(request))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.body.decode()), {"error": "確認文字列が一致しません。"})
        mock_delete.assert_not_called()

    # 日本語: test delete user account deletes account and clears session のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete user account deletes account and clears session.
    def test_delete_user_account_deletes_account_and_clears_session(self):
        session = {"user_id": 7, "user_email": "user@example.com"}
        request = build_request(
            method="DELETE",
            path="/api/user/account",
            session=session,
            json_body={"confirmation": ACCOUNT_DELETE_CONFIRMATION_TEXT},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.auth.delete_user_account", return_value=True) as mock_delete:
            response = asyncio.run(api_delete_user_account(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body.decode()), {"message": "アカウントを削除しました。"})
        self.assertEqual(session, {})
        mock_delete.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
