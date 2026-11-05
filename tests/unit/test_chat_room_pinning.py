"""チャットルームのピン留め（ChatRepository のピン操作・サイドバー用の整形・POST /api/pin_chat_room）を検証するテスト。

Tests chat room pinning: ChatRepository pin operations, sidebar serialization and the POST /api/pin_chat_room route.
"""

import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect

from blueprints.chat.rooms import pin_chat_room
from services.api_errors import ApiServiceError, ForbiddenOperationError
from services.models import ChatRoom
from services.repositories.chat_repository import ChatRepository
from services.repositories.chat_room_access import serialize_room
from tests.helpers.request_helpers import build_request


# SQLAlchemy の文を PostgreSQL 方言の SQL 文字列にして、生成された句を検証できるようにする。
# Compiles a SQLAlchemy statement to PostgreSQL SQL text so the generated clauses can be asserted.
def _compile(statement) -> str:
    return str(statement.compile(dialect=postgresql_dialect()))


# 最初の execute でルーム行を返し、続く execute には extra_results を順に返すセッションの代役を作る。
# Builds a fake session whose first execute returns the room row and later executes return extra_results in order.
def _session_returning_room(room: ChatRoom, *extra_results):
    room_result = Mock()
    room_result.scalar_one_or_none.return_value = room
    session = Mock()
    session.execute = AsyncMock(side_effect=[room_result, *extra_results])
    return session


# ChatRepository 層のピン留め: 一覧の振り分け、ピン時刻の更新、所有者・モードの検証。
# Pinning at the ChatRepository layer: list partitioning, pin timestamp updates, owner and mode validation.
class ChatRoomPinRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    # 通常の一覧はピン留め済みを除く（ピン留めは専用の一覧で別に返すため）。
    # The normal list excludes pinned rooms, since pinned rooms are returned by their own list.
    async def test_room_list_excludes_pinned_rooms(self):
        result = Mock()
        result.scalars.return_value.all.return_value = []
        session = Mock()
        session.execute = AsyncMock(return_value=result)

        await ChatRepository(session).list_user_rooms(7, limit=20)

        self.assertIn("chat_rooms.pinned_at IS NULL", _compile(session.execute.await_args.args[0]))

    # ピン留め一覧は新しくピンしたものが先頭で、一時チャット（temporary）は含めない。
    # The pinned list shows the newest pin first and excludes temporary rooms.
    async def test_pinned_list_orders_by_newest_pin(self):
        result = Mock()
        result.scalars.return_value.all.return_value = []
        session = Mock()
        session.execute = AsyncMock(return_value=result)

        await ChatRepository(session).list_pinned_user_rooms(7)

        sql = _compile(session.execute.await_args.args[0])
        self.assertIn("chat_rooms.pinned_at IS NOT NULL", sql)
        self.assertIn("chat_rooms.mode != ", sql)
        self.assertIn("ORDER BY chat_rooms.pinned_at DESC, chat_rooms.id DESC", sql)

    async def test_pin_stamps_current_time_and_returns_it(self):
        update_result = Mock()
        update_result.scalar_one.return_value = datetime(2026, 9, 23, 12, 0, 0)
        session = _session_returning_room(ChatRoom(id="room-1", user_id=7, mode="normal"), update_result)

        pinned_at = await ChatRepository(session).set_room_pinned("room-1", 7, True)

        self.assertEqual(pinned_at, "2026-09-23T12:00:00")
        sql = _compile(session.execute.await_args_list[1].args[0])
        self.assertIn("pinned_at=CURRENT_TIMESTAMP", sql)
        self.assertIn("RETURNING chat_rooms.pinned_at", sql)

    async def test_unpin_clears_the_pin(self):
        update_result = Mock()
        update_result.scalar_one.return_value = None
        room = ChatRoom(id="room-1", user_id=7, mode="normal", pinned_at=datetime(2026, 9, 1))
        session = _session_returning_room(room, update_result)

        pinned_at = await ChatRepository(session).set_room_pinned("room-1", 7, False)

        self.assertIsNone(pinned_at)
        statement = session.execute.await_args_list[1].args[0]
        self.assertNotIn("CURRENT_TIMESTAMP", _compile(statement))
        self.assertIsNone(statement.compile().params["pinned_at"])

    # すでにピン留め済みのルームを再度ピンしても時刻を更新せず、書き込みも行わない。
    # Pinning an already pinned room keeps its time and performs no write.
    async def test_repin_keeps_existing_time(self):
        room = ChatRoom(id="room-1", user_id=7, mode="normal", pinned_at=datetime(2026, 9, 1, 8, 30))
        session = _session_returning_room(room)

        pinned_at = await ChatRepository(session).set_room_pinned("room-1", 7, True)

        self.assertEqual(pinned_at, "2026-09-01T08:30:00")
        self.assertEqual(session.execute.await_count, 1)

    # 未ピンのルームのピン解除は書き込みを省く。
    # Unpinning a room that is not pinned skips the write.
    async def test_unpin_of_unpinned_room_skips_the_write(self):
        session = _session_returning_room(ChatRoom(id="room-1", user_id=7, mode="normal"))

        pinned_at = await ChatRepository(session).set_room_pinned("room-1", 7, False)

        self.assertIsNone(pinned_at)
        self.assertEqual(session.execute.await_count, 1)

    async def test_pin_rejects_other_users_room(self):
        session = _session_returning_room(ChatRoom(id="room-1", user_id=8, mode="normal"))

        with self.assertRaises(ForbiddenOperationError):
            await ChatRepository(session).set_room_pinned("room-1", 7, True)

    # 一時チャットはピン留めできない（400）。
    # Temporary rooms cannot be pinned (400).
    async def test_pin_rejects_temporary_room(self):
        session = _session_returning_room(ChatRoom(id="room-1", user_id=7, mode="temporary"))

        with self.assertRaises(ApiServiceError) as raised:
            await ChatRepository(session).set_room_pinned("room-1", 7, True)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(session.execute.await_count, 1)

    # サイドバー用の整形には pinned_at が入り、プロジェクト配下のルーム用には入らない。
    # The sidebar payload carries pinned_at; the project-room payload does not.
    def test_sidebar_payload_carries_pin_but_project_payload_does_not(self):
        room = ChatRoom(id="room-1", user_id=7, title="T", mode="normal", pinned_at=datetime(2026, 9, 1, 8, 30))

        self.assertEqual(serialize_room(room)["pinned_at"], "2026-09-01T08:30:00")
        self.assertNotIn("pinned_at", serialize_room(room, project_room=True))
        self.assertNotIn("pinnedAt", serialize_room(room, project_room=True))


# POST /api/pin_chat_room ルートの認証・入力検証・エラー転送。
# Authentication, input validation and error forwarding of the POST /api/pin_chat_room route.
class PinChatRoomRouteTestCase(unittest.TestCase):
    def _request(self, body, session=None):
        return build_request(
            method="POST",
            path="/api/pin_chat_room",
            json_body=body,
            session={"user_id": 7} if session is None else session,
        )

    def test_pin_returns_stored_time(self):
        with patch(
            "blueprints.chat.rooms.set_chat_room_pinned",
            new=AsyncMock(return_value="2026-09-23T12:00:00"),
        ) as set_pinned:
            response = asyncio.run(pin_chat_room(self._request({"room_id": "room-1", "pinned": True})))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body), {"room_id": "room-1", "pinned_at": "2026-09-23T12:00:00"})
        set_pinned.assert_awaited_once_with("room-1", 7, True)

    # 未ログイン（ゲスト）は 401 で、サービスを呼ばない。
    # A guest (not logged in) gets 401 and the service is never called.
    def test_guest_is_rejected(self):
        with patch("blueprints.chat.rooms.set_chat_room_pinned", new=AsyncMock()) as set_pinned:
            response = asyncio.run(pin_chat_room(self._request({"room_id": "room-1", "pinned": True}, session={})))

        self.assertEqual(response.status_code, 401)
        set_pinned.assert_not_awaited()

    # pinned フラグが無い要求は 400 で、サービスを呼ばない。
    # A request without the pinned flag gets 400 and the service is never called.
    def test_missing_pinned_flag_is_rejected(self):
        with patch("blueprints.chat.rooms.set_chat_room_pinned", new=AsyncMock()) as set_pinned:
            response = asyncio.run(pin_chat_room(self._request({"room_id": "room-1"})))

        self.assertEqual(response.status_code, 400)
        set_pinned.assert_not_awaited()

    def test_service_error_is_forwarded(self):
        with patch(
            "blueprints.chat.rooms.set_chat_room_pinned",
            new=AsyncMock(side_effect=ForbiddenOperationError("forbidden")),
        ):
            response = asyncio.run(pin_chat_room(self._request({"room_id": "room-1", "pinned": False})))

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
