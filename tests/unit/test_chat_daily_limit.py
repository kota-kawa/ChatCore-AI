import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.messages import chat
from tests.helpers.request_helpers import build_request


def make_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/chat",
        json_body=json_body,
        session=session,
    )


class ChatDailyLimitTestCase(unittest.TestCase):
    def test_chat_returns_429_when_guest_daily_limit_exceeded(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "default", "model": "gemini-2.5-flash"},
            session={"free_chats_count": "999999", "free_chats_date": "2099-01-01"},
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(False, "1日10回までです"),
            ) as mock_guest_limit:
                with patch("blueprints.chat.messages.ephemeral_store.room_exists") as mock_room_exists:
                    with patch("blueprints.chat.messages.consume_llm_daily_quota") as mock_llm_quota:
                        response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 429)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "1日10回までです")
        mock_guest_limit.assert_called_once_with(request)
        mock_room_exists.assert_not_called()
        mock_llm_quota.assert_not_called()

    def test_chat_returns_429_when_guest_daily_limit_exceeded_with_custom_message(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "default", "model": "gemini-2.5-flash"},
            session={},
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch(
                "blueprints.chat.messages.consume_guest_chat_daily_limit",
                return_value=(False, "1日3回までです"),
            ):
                response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 429)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "1日3回までです")

    def test_chat_returns_429_when_global_daily_limit_exceeded(self):
        request = make_request(
            {"message": "こんにちは", "chat_room_id": "default", "model": "gemini-2.5-flash"},
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
                            with patch(
                                "blueprints.chat.messages.consume_llm_daily_quota",
                                return_value=(False, 0, 300),
                            ):
                                with patch("blueprints.chat.messages.get_llm_response") as mock_llm:
                                    response = asyncio.run(chat(request))

        self.assertEqual(response.status_code, 429)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertIn("上限", payload["error"])
        mock_llm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
