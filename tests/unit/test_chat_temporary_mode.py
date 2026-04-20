import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.messages import chat
from blueprints.chat.rooms import new_chat_room
from starlette.responses import StreamingResponse
from tests.helpers.request_helpers import build_request


class ChatTemporaryModeTestCase(unittest.TestCase):
    def test_new_chat_room_creates_temporary_authenticated_room_in_ephemeral_store(self):
        request = build_request(
            method="POST",
            path="/api/new_chat_room",
            json_body={"id": "temp-room", "title": "Temp", "mode": "temporary"},
            session={"user_id": 7},
        )

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms.create_chat_room_in_db") as create_room:
                with patch("blueprints.chat.rooms.ephemeral_store.create_room") as create_ephemeral:
                    response = asyncio.run(new_chat_room(request))

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["mode"], "temporary")
        create_room.assert_called_once_with("temp-room", 7, "Temp", "temporary")
        create_ephemeral.assert_called_once_with("temporary-user:7", "temp-room", "Temp")

    def test_chat_uses_ephemeral_store_for_authenticated_temporary_room(self):
        request = build_request(
            method="POST",
            path="/api/chat",
            json_body={"message": "こんにちは", "chat_room_id": "temp-room", "model": "gpt-5-mini-2025-08-07"},
            session={"user_id": 11},
        )

        with patch("blueprints.chat.messages.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.messages.validate_room_owner", return_value="temporary"):
                with patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True):
                    with patch("blueprints.chat.messages.ephemeral_store.append_message") as append_message:
                        with patch(
                            "blueprints.chat.messages.ephemeral_store.get_messages",
                            return_value=[{"role": "user", "content": "こんにちは"}],
                        ):
                            with patch(
                                "blueprints.chat.messages.consume_llm_daily_quota",
                                return_value=(True, 1, 300),
                            ):
                                with patch("blueprints.chat.messages.is_streaming_model", return_value=False):
                                    with patch(
                                        "blueprints.chat.messages.get_llm_response",
                                        return_value="やあ",
                                    ):
                                        response = asyncio.run(chat(request))

        self.assertNotIsInstance(response, StreamingResponse)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["response"], "やあ")
        self.assertGreaterEqual(append_message.call_count, 2)


if __name__ == "__main__":
    unittest.main()
