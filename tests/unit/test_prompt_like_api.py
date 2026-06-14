import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import add_like, remove_like
from tests.helpers.request_helpers import build_request


# 日本語: make request の生成処理を担当します。
# English: Handle creating for make request.
def make_request(method, payload, session=None):
    return build_request(
        method=method,
        path="/prompt_share/api/like",
        json_body=payload,
        session=session,
    )


# 日本語: PromptLikeApiTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptLikeApiTestCase.
class PromptLikeApiTestCase(unittest.TestCase):
    # 日本語: test add like requires login のテスト検証を担当します。
    # English: Handle verifying test behavior for test add like requires login.
    def test_add_like_requires_login(self):
        request = make_request("POST", {"prompt_id": 10}, session={})

        response = asyncio.run(add_like(request))

        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "ログインしていません")

    # 日本語: test add like rejects missing prompt id のテスト検証を担当します。
    # English: Handle verifying test behavior for test add like rejects missing prompt id.
    def test_add_like_rejects_missing_prompt_id(self):
        request = make_request("POST", {}, session={"user_id": 5})

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.prompt_share.prompt_share_api._add_prompt_like_for_user") as mock_add:
            response = asyncio.run(add_like(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "必要なフィールドが不足しています")
        mock_add.assert_not_called()

    # 日本語: test add like returns created payload のテスト検証を担当します。
    # English: Handle verifying test behavior for test add like returns created payload.
    def test_add_like_returns_created_payload(self):
        request = make_request("POST", {"prompt_id": 10}, session={"user_id": 5})

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test remove like returns success payload のテスト検証を担当します。
    # English: Handle verifying test behavior for test remove like returns success payload.
    def test_remove_like_returns_success_payload(self):
        request = make_request("DELETE", {"prompt_id": 10}, session={"user_id": 5})

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.prompt_share.prompt_share_api._remove_prompt_like_for_user") as mock_remove:
            response = asyncio.run(remove_like(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertFalse(payload["liked"])
        self.assertEqual(payload["message"], "いいねを解除しました。")
        mock_remove.assert_called_once_with(5, 10)


if __name__ == "__main__":
    unittest.main()
