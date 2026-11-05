"""チャット共有トークンのサービス関数（作成・再利用・失効）が、リポジトリ操作と状態の整形を正しく行うことを検証するテスト。

Tests the chat share token service functions (create, reuse, revoke): repository delegation and state serialization.
"""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.chat_service import create_or_get_shared_chat_token, revoke_shared_chat_token


class ChatServiceSharedTokenTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_shared_token_service_uses_repository_operation(self):
        row = {"share_token": "existing-token", "expires_at": None, "revoked_at": None, "is_reused": True}
        with patch("services.chat_service._write", new=AsyncMock(return_value=row)) as write:
            state = await create_or_get_shared_chat_token("room-1", 3)

        self.assertEqual(state["share_token"], "existing-token")
        self.assertTrue(state["is_active"])
        self.assertTrue(state["is_reused"])
        write.assert_awaited_once()
        repository = Mock()
        repository.create_or_get_shared_chat_token = AsyncMock(return_value=row)
        operation = write.call_args.args[0]
        self.assertEqual(await operation(repository), row)
        repository.create_or_get_shared_chat_token.assert_awaited_once_with(
            "room-1", 3, expires_at=None, force_refresh=False
        )

    # 日数指定は、タイムゾーン付きの期限日時へ変換されてリポジトリへ渡される。
    # A day count is converted to a timezone-aware deadline before reaching the repository.
    async def test_expires_in_days_is_converted_to_an_aware_deadline(self):
        with patch("services.chat_service._write", new=AsyncMock(return_value=None)) as write:
            await create_or_get_shared_chat_token("room-1", 3, expires_in_days=7)

        repository = Mock()
        repository.create_or_get_shared_chat_token = AsyncMock(return_value=None)
        await write.call_args.args[0](repository)
        expires_at = repository.create_or_get_shared_chat_token.await_args.kwargs["expires_at"]
        self.assertIsNotNone(expires_at.tzinfo)
        self.assertAlmostEqual(
            (expires_at - datetime.now(UTC)).total_seconds(),
            timedelta(days=7).total_seconds(),
            delta=60,
        )

    # ルーム未存在・他人のルームの例外を別の例外へ変換しない（API 層が 404/403 にするため）。
    # Not-found and forbidden errors are not converted to other exceptions, so the API layer can map them to 404/403.
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

    async def test_revoke_serializes_the_revoked_state(self):
        revoked_at = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
        row = {"share_token": "old-token", "expires_at": None, "revoked_at": revoked_at}
        with patch("services.chat_service._write", new=AsyncMock(return_value=row)):
            state = await revoke_shared_chat_token("room-1", 3)

        self.assertTrue(state["is_revoked"])
        self.assertFalse(state["is_active"])
        self.assertEqual(state["revoked_at"], revoked_at.isoformat())

    # 一度も共有していないルームの失効は None を返す。
    # Revoking a room that was never shared returns None.
    async def test_revoke_returns_none_when_the_room_was_never_shared(self):
        with patch("services.chat_service._write", new=AsyncMock(return_value=None)):
            self.assertIsNone(await revoke_shared_chat_token("room-1", 3))

    async def test_revoke_does_not_convert_ownership_errors(self):
        with patch(
            "services.chat_service._write",
            new=AsyncMock(side_effect=ForbiddenOperationError("他ユーザーのチャットルームは共有できません")),
        ):
            with self.assertRaises(ForbiddenOperationError):
                await revoke_shared_chat_token("room-1", 10)


if __name__ == "__main__":
    unittest.main()
