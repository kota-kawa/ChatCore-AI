import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.messages import chat
from blueprints.chat.rooms import get_chat_rooms, new_chat_room
from starlette.responses import StreamingResponse
from tests.helpers.request_helpers import build_request


class ChatTemporaryModeTestCase(unittest.TestCase):
    def test_new_chat_room_creates_temporary_authenticated_room_without_db_persistence(self):
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
        create_room.assert_not_called()
        create_ephemeral.assert_called_once_with("temporary-user:7", "temp-room", "Temp")

    def test_get_chat_rooms_returns_only_persisted_rooms(self):
        request = build_request(
            method="GET",
            path="/api/get_chat_rooms",
            session={"user_id": 7},
        )

        persisted_rooms = [
            {
                "id": "room-normal",
                "title": "保存チャット",
                "mode": "normal",
                "created_at": "2026-04-20T10:00:00+09:00",
            }
        ]

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            with patch("blueprints.chat.rooms._fetch_persisted_user_rooms", return_value=persisted_rooms):
                response = asyncio.run(get_chat_rooms(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual([room["id"] for room in payload["rooms"]], ["room-normal"])

    def test_chat_uses_ephemeral_store_for_authenticated_temporary_room(self):
        request = build_request(
            method="POST",
            path="/api/chat",
            json_body={"message": "こんにちは", "chat_room_id": "temp-room", "model": "gpt-5-mini-2025-08-07"},
            session={"user_id": 11},
        )

        with (
            patch("blueprints.chat.messages.cleanup_ephemeral_chats"),
            patch("blueprints.chat.messages.validate_room_owner", return_value="temporary"),
            patch("blueprints.chat.messages.ephemeral_store.room_exists", return_value=True),
            patch("blueprints.chat.messages.ephemeral_store.append_message") as append_message,
            patch(
                "blueprints.chat.messages.ephemeral_store.get_messages",
                return_value=[{"role": "user", "content": "こんにちは"}],
            ),
            patch("blueprints.chat.messages.get_user_by_id", return_value={}),
            patch(
                "blueprints.chat.messages.consume_llm_daily_quota",
                return_value=(True, 1, 300),
            ),
            patch("blueprints.chat.messages.is_streaming_model", return_value=False),
            patch("blueprints.chat.messages.get_llm_response", return_value="やあ"),
        ):
            response = asyncio.run(chat(request))

        self.assertNotIsInstance(response, StreamingResponse)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["response"], "やあ")
        self.assertGreaterEqual(append_message.call_count, 2)


if __name__ == "__main__":
    unittest.main()
