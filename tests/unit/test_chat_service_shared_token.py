import unittest
from unittest.mock import AsyncMock, Mock, patch

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.chat_service import create_or_get_shared_chat_token


class ChatServiceSharedTokenTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_shared_token_service_uses_repository_operation(self):
        with patch("services.chat_service._write", new=AsyncMock(return_value="existing-token")) as write:
            token = await create_or_get_shared_chat_token("room-1", 3)

        self.assertEqual(token, "existing-token")
        write.assert_awaited_once()
        repository = Mock()
        repository.create_or_get_shared_chat_token = AsyncMock(return_value="repo-token")
        operation = write.call_args.args[0]
        self.assertEqual(await operation(repository), "repo-token")
        repository.create_or_get_shared_chat_token.assert_awaited_once_with("room-1", 3)

    async def test_missing_or_forbidden_room_errors_are_not_converted(self):
        for error in (
            ResourceNotFoundError("該当ルームが見つかりません"),
            ForbiddenOperationError("他ユーザーのチャットルームは共有できません"),
        ):
            with self.subTest(error=type(error).__name__), patch(
                "services.chat_service._write",
                new=AsyncMock(side_effect=error),
            ):
                with self.assertRaises(type(error)):
                    await create_or_get_shared_chat_token("room-1", 10)


if __name__ == "__main__":
    unittest.main()
