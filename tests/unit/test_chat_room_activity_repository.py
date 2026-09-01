import unittest
from datetime import datetime
from unittest.mock import AsyncMock, Mock

from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect

from services.models import ChatHistory, ChatRoom
from services.repositories.chat_repository import ChatRepository


def _compile(statement) -> str:
    return str(statement.compile(dialect=postgresql_dialect()))


class ChatRoomActivityRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_room_list_uses_last_activity_for_order_and_cursor(self):
        result = Mock()
        result.scalars.return_value.all.return_value = []
        session = Mock()
        session.execute = AsyncMock(return_value=result)

        await ChatRepository(session).list_user_rooms(
            7,
            limit=20,
            cursor=(datetime(2026, 9, 1, 12, 0, 0), "room-20"),
        )

        statement = session.execute.await_args.args[0]
        sql = _compile(statement)
        self.assertIn("chat_rooms.last_activity_at <", sql)
        self.assertIn("chat_rooms.last_activity_at =", sql)
        self.assertIn(
            "ORDER BY chat_rooms.last_activity_at DESC, chat_rooms.id DESC",
            sql,
        )

    async def test_root_message_updates_room_activity(self):
        room_result = Mock()
        room_result.scalar_one_or_none.return_value = ChatRoom(id="room-1", user_id=7)
        session = Mock()
        session.execute = AsyncMock(side_effect=[room_result, Mock()])
        session.flush = AsyncMock()

        await ChatRepository(session).save_message("room-1", "hello", "user")

        room_update = session.execute.await_args_list[1].args[0]
        sql = _compile(room_update)
        self.assertIn("last_activity_at=CURRENT_TIMESTAMP", sql)
        self.assertIn("active_root_id=", sql)

    async def test_branch_message_updates_room_activity(self):
        parent_result = Mock()
        parent_result.scalar_one_or_none.return_value = ChatHistory(
            id=9,
            chat_room_id="room-1",
            message="previous",
            sender="assistant",
        )
        session = Mock()
        session.execute = AsyncMock(side_effect=[parent_result, Mock(), Mock()])
        session.flush = AsyncMock()

        await ChatRepository(session).save_message(
            "room-1",
            "continued",
            "user",
            parent_id=9,
        )

        room_update = session.execute.await_args_list[2].args[0]
        self.assertIn("last_activity_at=CURRENT_TIMESTAMP", _compile(room_update))


if __name__ == "__main__":
    unittest.main()
