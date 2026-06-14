import asyncio
import json
import unittest
from unittest.mock import patch

from services.api_errors import ApiServiceError
from blueprints.chat.rooms import _delete_rooms_for_user, delete_chat_rooms
from tests.helpers.request_helpers import build_request


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, rows):
        self.rows = rows
        self.executed = []
        self.closed = False

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        self.executed.append((query, params))

    # 日本語: fetchall に関する処理の入口です。
    # English: Entry point for logic related to fetchall.
    def fetchall(self):
        return self.rows

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: FakeConnection に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeConnection.
class FakeConnection:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, rows):
        self.cursor_instance = FakeCursor(rows)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    # 日本語: cursor に関する処理の入口です。
    # English: Entry point for logic related to cursor.
    def cursor(self):
        return self.cursor_instance

    # 日本語: commit に関する処理の入口です。
    # English: Entry point for logic related to commit.
    def commit(self):
        self.committed = True

    # 日本語: rollback に関する処理の入口です。
    # English: Entry point for logic related to rollback.
    def rollback(self):
        self.rolled_back = True

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: ChatRoomBulkDeleteTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatRoomBulkDeleteTestCase.
class ChatRoomBulkDeleteTestCase(unittest.TestCase):
    # 日本語: test delete rooms for user deletes history and rooms after owner validation のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete rooms for user deletes history and rooms after owner validation.
    def test_delete_rooms_for_user_deletes_history_and_rooms_after_owner_validation(self):
        connection = FakeConnection([("room-1", 7), ("room-2", 7)])

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.rooms.get_db_connection", return_value=connection):
            result = _delete_rooms_for_user(["room-1", "room-2", "room-1"], 7)

        self.assertEqual(result["deleted_count"], 2)
        self.assertEqual(result["deleted_room_ids"], ["room-1", "room-2"])
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        self.assertEqual(len(connection.cursor_instance.executed), 3)
        self.assertIn("SELECT id, user_id FROM chat_rooms", connection.cursor_instance.executed[0][0])
        self.assertIn("DELETE FROM chat_history", connection.cursor_instance.executed[1][0])
        self.assertIn("DELETE FROM chat_rooms", connection.cursor_instance.executed[2][0])
        self.assertEqual(connection.cursor_instance.executed[0][1], ("room-1", "room-2"))
        self.assertTrue(connection.cursor_instance.closed)
        self.assertTrue(connection.closed)

    # 日本語: test delete rooms for user rejects missing room without delete のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete rooms for user rejects missing room without delete.
    def test_delete_rooms_for_user_rejects_missing_room_without_delete(self):
        connection = FakeConnection([("room-1", 7)])

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.rooms.get_db_connection", return_value=connection):
            with self.assertRaises(ApiServiceError) as exc_info:
                _delete_rooms_for_user(["room-1", "missing-room"], 7)

        self.assertEqual(exc_info.exception.status_code, 404)
        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)
        self.assertEqual(len(connection.cursor_instance.executed), 1)

    # 日本語: test delete rooms for user rejects other users room without delete のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete rooms for user rejects other users room without delete.
    def test_delete_rooms_for_user_rejects_other_users_room_without_delete(self):
        connection = FakeConnection([("room-1", 7), ("room-2", 99)])

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.rooms.get_db_connection", return_value=connection):
            with self.assertRaises(ApiServiceError) as exc_info:
                _delete_rooms_for_user(["room-1", "room-2"], 7)

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)
        self.assertEqual(len(connection.cursor_instance.executed), 1)

    # 日本語: test delete chat rooms requires login のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete chat rooms requires login.
    def test_delete_chat_rooms_requires_login(self):
        request = build_request(
            method="POST",
            path="/api/delete_chat_rooms",
            json_body={"room_ids": ["room-1"]},
            session={},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            response = asyncio.run(delete_chat_rooms(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", payload)

    # 日本語: test delete chat rooms returns bulk delete payload のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete chat rooms returns bulk delete payload.
    def test_delete_chat_rooms_returns_bulk_delete_payload(self):
        request = build_request(
            method="POST",
            path="/api/delete_chat_rooms",
            json_body={"room_ids": ["room-1", "room-2"]},
            session={"user_id": 7},
        )

        response_payload = {
            "message": "削除しました",
            "deleted_count": 2,
            "deleted_room_ids": ["room-1", "room-2"],
        }
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with (
            patch("blueprints.chat.rooms.cleanup_ephemeral_chats"),
            patch("blueprints.chat.rooms._delete_rooms_for_user", return_value=response_payload) as delete_rooms,
        ):
            response = asyncio.run(delete_chat_rooms(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload, response_payload)
        delete_rooms.assert_called_once_with(["room-1", "room-2"], 7)


if __name__ == "__main__":
    unittest.main()
