import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import add_like, remove_like
from tests.helpers.request_helpers import build_request


# いいね操作のAPIテスト用のHTTPリクエストを構築します。
# Build a mock HTTP request for testing prompt like API endpoints.
def make_request(method, payload, session=None):
    return build_request(
        method=method,
        path="/prompt_share/api/like",
        json_body=payload,
        session=session,
    )


# プロンプトに対する「いいね」の追加や削除（解除）に関するAPIエンドポイントをテストするクラス。
# Test class to check the API endpoints for adding and removing likes on prompts.
class PromptLikeApiTestCase(unittest.TestCase):
    # ログインしていない状態で「いいね」を追加しようとすると、401エラー（未認証）になることを検証します。
    # Verify that adding a like returns a 401 status when the user is not logged in.
    def test_add_like_requires_login(self):
        request = make_request("POST", {"prompt_id": 10}, session={})

        response = asyncio.run(add_like(request))

        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "ログインしていません")

    # リクエストボディにprompt_idが不足している場合、400エラーで拒否されることを検証します。
    # Verify that adding a like returns a 400 status when the prompt_id is missing from the payload.
    def test_add_like_rejects_missing_prompt_id(self):
        request = make_request("POST", {}, session={"user_id": 5})

        # いいね追加処理が呼び出されないことをモックで確認
        # Verify that the DB helper is not called using mocks
        with patch("blueprints.prompt_share.prompt_share_api._add_prompt_like_for_user") as mock_add:
            response = asyncio.run(add_like(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "必要なフィールドが不足しています")
        mock_add.assert_not_called()

    # 正常に「いいね」を追加できた場合に、201ステータスと更新されたステータス情報を返すことを検証します。
    # Verify that successfully adding a like returns a 201 status and the updated status payload.
    def test_add_like_returns_created_payload(self):
        request = make_request("POST", {"prompt_id": 10}, session={"user_id": 5})

        # いいね登録の戻り値をモック
        # Mock the helper response for adding a like
        with patch(
            "blueprints.prompt_share.prompt_share_api._add_prompt_like_for_user",
            return_value=({"message": "いいねしました。", "liked": True}, 201),
        ) as mock_add:
            response = asyncio.run(add_like(request))

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["liked"])
        self.assertEqual(payload["message"], "いいねしました。")
        mock_add.assert_called_once_with(5, 10)

    # 「いいね」を正常に解除できた場合に、200ステータスと解除成功情報を返すことを検証します。
    # Verify that successfully removing a like returns a 200 status and the updated status payload.
    def test_remove_like_returns_success_payload(self):
        request = make_request("DELETE", {"prompt_id": 10}, session={"user_id": 5})

        # いいね削除処理をモック
        # Mock the helper for removing a like
        with patch("blueprints.prompt_share.prompt_share_api._remove_prompt_like_for_user") as mock_remove:
            response = asyncio.run(remove_like(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertFalse(payload["liked"])
        self.assertEqual(payload["message"], "いいねを解除しました。")
        mock_remove.assert_called_once_with(5, 10)


if __name__ == "__main__":
    unittest.main()
