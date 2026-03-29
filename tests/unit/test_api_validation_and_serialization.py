import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from blueprints.auth import api_send_login_code
from blueprints.chat.messages import chat
from blueprints.chat.tasks import update_tasks_order
from blueprints.prompt_share.prompt_manage_api import get_my_prompts
from tests.helpers.request_helpers import build_request


def make_request(
    *,
    method: str,
    path: str,
    session=None,
    json_body=None,
    raw_body: bytes | None = None,
):
    return build_request(
        method=method,
        path=path,
        session=session,
        json_body=json_body,
        raw_body=raw_body,
    )


class ApiValidationAndSerializationTestCase(unittest.TestCase):
    def test_chat_update_tasks_order_rejects_malformed_json(self):
        request = make_request(
            method="POST",
            path="/api/update_tasks_order",
            session={"user_id": 1},
            raw_body=b"{",
        )

        response = asyncio.run(update_tasks_order(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "JSON形式が不正です。")

    def test_auth_send_login_code_rejects_malformed_json_with_fail_status(self):
        request = make_request(
            method="POST",
            path="/api/send_login_code",
            raw_body=b"{",
        )

        response = asyncio.run(api_send_login_code(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "JSON形式が不正です。")

    def test_chat_missing_ephemeral_room_returns_404_response(self):
        request = make_request(
            method="POST",
            path="/api/chat",
            json_body={"message": "こんにちは", "chat_room_id": "missing-room"},
            session={},
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=False):
                    response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 404)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "該当ルームが見つかりません")

    def test_chat_returns_400_when_invalid_model_is_requested(self):
        request = make_request(
            method="POST",
            path="/api/chat",
            json_body={"message": "こんにちは", "chat_room_id": "room-1", "model": "invalid-model"},
            session={},
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(True, None),
            ):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True):
                    with patch("blueprints.chat.messages.ephemeral_store.get_messages", return_value=[]):
                        with patch("blueprints.chat.messages.ephemeral_store.append_message"):
                            with patch("blueprints.chat.messages.consume_llm_daily_quota") as mock_quota:
                                with patch("blueprints.chat.messages.get_llm_response") as mock_llm:
                                    response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertIn("無効なモデル", payload["error"])
        mock_quota.assert_not_called()
        mock_llm.assert_not_called()

    def test_prompt_manage_serializes_datetime_consistently(self):
        request = make_request(
            method="GET",
            path="/prompt_manage/api/my_prompts",
            session={"user_id": 99},
        )
        sample_prompts = [
            {
                "id": 1,
                "title": "title",
                "category": "cat",
                "content": "content",
                "input_examples": "",
                "output_examples": "",
                "created_at": datetime(2024, 1, 2, 3, 4, 5),
            }
        ]

        with patch(
            "blueprints.prompt_share.prompt_manage_api._fetch_my_prompts",
            return_value=sample_prompts,
        ):
            response = asyncio.run(get_my_prompts(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["prompts"][0]["created_at"], "2024-01-02T03:04:05")


if __name__ == "__main__":
    unittest.main()
