import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from blueprints.chat.rooms import (
    _encode_room_list_cursor,
    _fetch_persisted_user_rooms,
    get_chat_rooms,
    new_chat_room,
)
from tests.helpers.request_helpers import build_request


class ChatTemporaryModeTestCase(unittest.TestCase):
    def test_new_chat_room_uses_ephemeral_store_for_temporary_mode(self):
        request = build_request(
            method="POST",
            path="/api/new_chat_room",
            json_body={"id": "temp-room", "title": "Temp", "mode": "temporary"},
            session={"user_id": 7},
        )
        with (
            patch("blueprints.chat.rooms.cleanup_ephemeral_chats"),
            patch("blueprints.chat.rooms.create_chat_room_in_db") as create_room,
            patch("blueprints.chat.rooms.ephemeral_store.create_room") as create_ephemeral,
        ):
            response = asyncio.run(new_chat_room(request))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(json.loads(response.body)["mode"], "temporary")
        create_room.assert_not_called()
        create_ephemeral.assert_called_once_with("temporary-user:7", "temp-room", "Temp")

    def test_get_chat_rooms_delegates_persisted_list_with_limit_plus_one(self):
        request = build_request(
            method="GET",
            path="/api/get_chat_rooms",
            query_string=b"limit=20",
            session={"user_id": 7},
        )
        rooms = [
            {"id": f"room-{index}", "title": f"Room {index}", "mode": "normal", "created_at": "2026-04-20T10:00:00+09:00"}
            for index in range(21)
        ]
        with (
            patch("blueprints.chat.rooms.cleanup_ephemeral_chats"),
            patch("blueprints.chat.rooms._fetch_persisted_user_rooms", new=AsyncMock(return_value=rooms)) as fetch,
        ):
            response = asyncio.run(get_chat_rooms(request))

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["rooms"]), 20)
        self.assertTrue(payload["pagination"]["has_more"])
        fetch.assert_awaited_once_with(7, limit=21, cursor=None)

    def test_get_chat_rooms_passes_decoded_cursor(self):
        cursor = _encode_room_list_cursor({"id": "room-20", "created_at": "2026-04-20T10:00:00"})
        request = build_request(
            method="GET",
            path="/api/get_chat_rooms",
            query_string=f"limit=20&cursor={cursor}".encode(),
            session={"user_id": 7},
        )
        with (
            patch("blueprints.chat.rooms.cleanup_ephemeral_chats"),
            patch("blueprints.chat.rooms._fetch_persisted_user_rooms", new=AsyncMock(return_value=[])) as fetch,
        ):
            response = asyncio.run(get_chat_rooms(request))

        self.assertEqual(response.status_code, 200)
        fetch.assert_awaited_once_with(
            7,
            limit=21,
            cursor=(datetime(2026, 4, 20, 10, 0, 0), "room-20"),
        )

    def test_fetch_persisted_user_rooms_delegates_async_service(self):
        cursor = (datetime(2026, 4, 20, 10, 0, 0), "room-20")
        persisted = [{"id": "room-21", "title": "Room 21", "mode": "normal"}]
        with patch("blueprints.chat.rooms.list_chat_rooms", new=AsyncMock(return_value=persisted)) as fetch:
            rooms = asyncio.run(_fetch_persisted_user_rooms(7, limit=21, cursor=cursor))

        self.assertEqual(rooms, persisted)
        fetch.assert_awaited_once_with(7, limit=21, cursor=cursor)


if __name__ == "__main__":
    unittest.main()
