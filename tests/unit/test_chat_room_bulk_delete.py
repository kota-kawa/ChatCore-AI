import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from blueprints.chat.rooms import _delete_rooms_for_user, delete_chat_rooms
from services.api_errors import ResourceNotFoundError
from tests.helpers.request_helpers import build_request


class ChatRoomBulkDeleteTestCase(unittest.TestCase):
    def test_bulk_delete_delegates_one_atomic_use_case(self):
        result = {
            "message": "削除しました",
            "deleted_count": 2,
            "deleted_room_ids": ["room-1", "room-2"],
        }
        with patch(
            "blueprints.chat.rooms.delete_chat_rooms_for_user",
            new=AsyncMock(return_value=result),
        ) as delete_rooms:
            actual = asyncio.run(_delete_rooms_for_user(["room-1", "room-2", "room-1"], 7))

        self.assertEqual(actual, result)
        delete_rooms.assert_awaited_once_with(["room-1", "room-2", "room-1"], 7)

    def test_bulk_delete_propagates_transaction_error_without_dbapi_fixture(self):
        with patch(
            "blueprints.chat.rooms.delete_chat_rooms_for_user",
            new=AsyncMock(side_effect=ResourceNotFoundError("missing")),
        ):
            with self.assertRaises(ResourceNotFoundError):
                asyncio.run(_delete_rooms_for_user(["missing"], 7))

    def test_delete_route_returns_service_payload(self):
        request = build_request(
            method="POST",
            path="/api/delete_chat_rooms",
            json_body={"room_ids": ["room-1", "room-2"]},
            session={"user_id": 7},
        )
        result = {
            "message": "削除しました",
            "deleted_count": 2,
            "deleted_room_ids": ["room-1", "room-2"],
        }
        with (
            patch("blueprints.chat.rooms.cleanup_ephemeral_chats"),
            patch(
                "blueprints.chat.rooms._delete_rooms_for_user",
                new=AsyncMock(return_value=result),
            ) as delete_rooms,
        ):
            response = asyncio.run(delete_chat_rooms(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body), result)
        delete_rooms.assert_awaited_once_with(["room-1", "room-2"], 7)


if __name__ == "__main__":
    unittest.main()
