import unittest
from unittest.mock import AsyncMock, patch

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.chat_service import validate_room_owner


class ChatRoomOwnerValidationTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_validate_room_owner_propagates_missing_room_error(self):
        with patch(
            "services.chat_service._read",
            new=AsyncMock(side_effect=ResourceNotFoundError("該当ルームが見つかりません")),
        ):
            with self.assertRaises(ResourceNotFoundError) as exc_info:
                await validate_room_owner("missing-room", 1, "forbidden")

        self.assertEqual(exc_info.exception.status_code, 404)

    async def test_validate_room_owner_propagates_forbidden_error(self):
        with patch(
            "services.chat_service._read",
            new=AsyncMock(side_effect=ForbiddenOperationError("forbidden")),
        ):
            with self.assertRaises(ForbiddenOperationError) as exc_info:
                await validate_room_owner("room-1", 1, "forbidden")

        self.assertEqual(exc_info.exception.status_code, 403)

    async def test_validate_room_owner_returns_mode_from_repository(self):
        with patch("services.chat_service._read", new=AsyncMock(return_value="normal")) as read:
            result = await validate_room_owner("room-1", 1, "forbidden")

        self.assertEqual(result, "normal")
        read.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
