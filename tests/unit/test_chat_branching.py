import unittest
from unittest.mock import AsyncMock, Mock, patch

from services.chat_service import save_message_to_db, switch_chat_branch
from services.repositories.chat_repository import ChatRepository


class ChatBranchingTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_write_service_keeps_external_session_transaction_open(self):
        session = Mock()
        with patch("services.chat_service._write", new=AsyncMock(return_value=17)) as write:
            message_id = await save_message_to_db(
                "room-1",
                "hello",
                "user",
                parent_id=4,
                session=session,
            )

        self.assertEqual(message_id, 17)
        self.assertIs(write.call_args.args[1], session)
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    async def test_branch_switch_is_delegated_to_repository_with_external_session(self):
        session = Mock()
        with patch("services.chat_service._write", new=AsyncMock(return_value=[])) as write:
            result = await switch_chat_branch("room-1", 8, session=session)

        self.assertEqual(result, [])
        self.assertIs(write.call_args.args[1], session)
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    def test_active_path_projection_follows_active_child_chain(self):
        repository = ChatRepository(Mock())
        nodes = {
            1: {"id": 1, "parent_id": None, "active_child_id": 2, "sender": "user", "message": "hi"},
            2: {"id": 2, "parent_id": 1, "active_child_id": 3, "sender": "assistant", "message": "hello"},
            3: {"id": 3, "parent_id": 2, "active_child_id": None, "sender": "user", "message": "next"},
            4: {"id": 4, "parent_id": 1, "active_child_id": None, "sender": "assistant", "message": "other"},
        }

        children = repository._children_by_parent(nodes)
        path = repository._walk_active_path(nodes, 1, children)

        self.assertEqual([node["id"] for node in path], [1, 2, 3])
        self.assertEqual(children[1], [2, 4])


if __name__ == "__main__":
    unittest.main()
