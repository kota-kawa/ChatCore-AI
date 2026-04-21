import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import add_like, remove_like
from tests.helpers.request_helpers import build_request


def make_request(method, payload, session=None):
    return build_request(
        method=method,
        path="/prompt_share/api/like",
        json_body=payload,
        session=session,
    )


class PromptLikeApiTestCase(unittest.TestCase):
    def test_add_like_requires_login(self):
        request = make_request("POST", {"prompt_id": 10}, session={})

        response = asyncio.run(add_like(request))

        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "ログインしていません")

    def test_add_like_rejects_missing_prompt_id(self):
        request = make_request("POST", {}, session={"user_id": 5})

        with patch("blueprints.prompt_share.prompt_share_api._add_prompt_like_for_user") as mock_add:
            response = asyncio.run(add_like(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "必要なフィールドが不足しています")
        mock_add.assert_not_called()

    def test_add_like_returns_created_payload(self):
        request = make_request("POST", {"prompt_id": 10}, session={"user_id": 5})

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

    def test_remove_like_returns_success_payload(self):
        request = make_request("DELETE", {"prompt_id": 10}, session={"user_id": 5})

        with patch("blueprints.prompt_share.prompt_share_api._remove_prompt_like_for_user") as mock_remove:
            response = asyncio.run(remove_like(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertFalse(payload["liked"])
        self.assertEqual(payload["message"], "いいねを解除しました。")
        mock_remove.assert_called_once_with(5, 10)


if __name__ == "__main__":
    unittest.main()
