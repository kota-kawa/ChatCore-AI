import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from blueprints.chat.rooms import MAX_FORKED_MESSAGES, fork_shared_chat_room
from services.chat_service import fork_shared_chat_into_db_room
from services.api_errors import ResourceNotFoundError
from tests.helpers.request_helpers import build_request


SHARED_PAYLOAD = {
    "room": {"id": "room-1", "title": "共有された会話"},
    "messages": [
        {"message": "こんにちは", "sender": "user"},
        {
            "message": "はい、どうぞ",
            "sender": "assistant",
            "message_parts": [{"type": "text", "text": "はい、どうぞ"}],
        },
    ],
}


def make_fork_request(json_body, session=None):
    return build_request(
        method="POST",
        path="/api/fork_shared_chat_room",
        json_body=json_body,
        session=session if session is not None else {},
    )


class SharedChatForkServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_fork_composes_room_and_message_repositories(self):
        with patch("services.chat_service._write", new=AsyncMock()) as write:
            await fork_shared_chat_into_db_room("token-1", "room-new", 7)

        repository = Mock()
        repository.get_shared_chat_room_payload = AsyncMock(return_value=SHARED_PAYLOAD)
        repository.create_room = AsyncMock()
        repository.copy_messages_into_room = AsyncMock(return_value=2)
        operation = write.call_args.args[0]
        actual = await operation(repository)

        self.assertEqual(
            actual,
            {"id": "room-new", "title": "共有された会話", "mode": "normal", "message_count": 2},
        )
        repository.create_room.assert_awaited_once_with("room-new", 7, "共有された会話", "normal")
        repository.copy_messages_into_room.assert_awaited_once()
        self.assertEqual(len(repository.copy_messages_into_room.call_args.args[1]), 2)

    async def test_fork_caps_messages_before_repository_write(self):
        payload = {
            "room": {"title": "長い会話"},
            "messages": [{"message": str(index), "sender": "user"} for index in range(MAX_FORKED_MESSAGES + 25)],
        }
        with patch("services.chat_service._write", new=AsyncMock()) as write:
            await fork_shared_chat_into_db_room("token-1", "room-new", 7)

        repository = Mock()
        repository.get_shared_chat_room_payload = AsyncMock(return_value=payload)
        repository.create_room = AsyncMock()
        repository.copy_messages_into_room = AsyncMock(return_value=MAX_FORKED_MESSAGES)
        await write.call_args.args[0](repository)
        self.assertEqual(
            len(repository.copy_messages_into_room.call_args.args[1]),
            MAX_FORKED_MESSAGES,
        )

class ForkSharedChatRoomRouteTestCase(unittest.TestCase):
    def test_authenticated_viewer_forks_into_own_room(self):
        request = make_fork_request({"token": "token-1", "id": "room-new"}, session={"user_id": 42})
        result = {"id": "room-new", "title": "共有された会話", "mode": "normal", "message_count": 2}
        with (
            patch("blueprints.chat.rooms.cleanup_ephemeral_chats"),
            patch("blueprints.chat.rooms.fork_shared_chat_into_db_room", new=AsyncMock(return_value=result)) as fork,
        ):
            response = asyncio.run(fork_shared_chat_room(request))

        fork.assert_awaited_once_with("token-1", "room-new", 42)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(json.loads(response.body)["mode"], "normal")

    def test_guest_viewer_forks_into_temporary_room(self):
        session = {"sid": "sid-1"}
        request = make_fork_request({"token": "token-1", "id": "room-new"}, session=session)
        result = {"id": "room-new", "title": "共有チャット", "mode": "temporary", "message_count": 2}
        with (
            patch("blueprints.chat.rooms.cleanup_ephemeral_chats"),
            patch("blueprints.chat.rooms.consume_guest_chat_daily_limit", return_value=(True, "")),
            patch("blueprints.chat.rooms._fork_shared_chat_into_ephemeral_room", new=AsyncMock(return_value=result)),
        ):
            response = asyncio.run(fork_shared_chat_room(request))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(json.loads(response.body)["mode"], "temporary")
        self.assertIn("room-new", session.get("guest_room_ids", []))

    def test_guest_viewer_is_rate_limited_before_copy(self):
        request = make_fork_request({"token": "token-1", "id": "room-new"}, session={"sid": "sid-1"})
        with (
            patch("blueprints.chat.rooms.cleanup_ephemeral_chats"),
            patch("blueprints.chat.rooms.consume_guest_chat_daily_limit", return_value=(False, "上限です")),
            patch("blueprints.chat.rooms._fork_shared_chat_into_ephemeral_room", new=AsyncMock()) as fork,
        ):
            response = asyncio.run(fork_shared_chat_room(request))

        fork.assert_not_awaited()
        self.assertEqual(response.status_code, 429)

    def test_unknown_token_returns_not_found(self):
        request = make_fork_request({"token": "missing", "id": "room-new"}, session={"user_id": 1})
        with (
            patch("blueprints.chat.rooms.cleanup_ephemeral_chats"),
            patch(
                "blueprints.chat.rooms.fork_shared_chat_into_db_room",
                new=AsyncMock(side_effect=ResourceNotFoundError("共有リンクが見つかりません")),
            ),
        ):
            response = asyncio.run(fork_shared_chat_room(request))

        self.assertEqual(response.status_code, 404)

    def test_missing_token_is_rejected(self):
        request = make_fork_request({"id": "room-new"}, session={"user_id": 1})
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            response = asyncio.run(fork_shared_chat_room(request))
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
