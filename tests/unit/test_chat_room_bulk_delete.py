import asyncio
import json
import unittest
from unittest.mock import patch

from services.api_errors import ApiServiceError
from blueprints.chat.rooms import _delete_rooms_for_user, delete_chat_rooms
from tests.helpers.request_helpers import build_request


# 一括削除処理をテストするための疑似DBカーソルクラス。
# Mock database cursor class for testing bulk deletion of chat rooms.
class FakeCursor:
    # インスタンス生成時に必要な初期状態を設定します。
    # Initialize the required instance state when the object is created.
    def __init__(self, rows):
        self.rows = rows
        self.executed = []
        self.closed = False

    # クエリを実行し、引数を記録します。
    # Execute a query and record arguments.
    def execute(self, query, params=None):
        self.executed.append((query, params))

    # モックの取得結果を返却します。
    # Return mock fetch results.
    def fetchall(self):
        return self.rows

    # カーソルを閉じます。
    # Close the cursor.
    def close(self):
        self.closed = True


# 一括削除処理をテストするための疑似DBコネクションクラス。
# Mock database connection class for testing bulk deletion of chat rooms.
class FakeConnection:
    # インスタンス生成時に必要な初期状態を設定します。
    # Initialize the required instance state when the object is created.
    def __init__(self, rows):
        self.cursor_instance = FakeCursor(rows)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    # カーソルを返却します。
    # Return the cursor.
    def cursor(self):
        return self.cursor_instance

    # コミットされたことを記録します。
    # Commit the transaction.
    def commit(self):
        self.committed = True

    # ロールバックされたことを記録します。
    # Rollback the transaction.
    def rollback(self):
        self.rolled_back = True

    # コネクションを閉じます。
    # Close the connection.
    def close(self):
        self.closed = True


# チャットルームのまとめて削除（バルク削除）処理におけるトランザクション制御や、権限チェック、エラー時のロールバックをテストするクラス。
# Test class to check transaction control, authorization checks, and rollback on error during bulk chat room deletion.
class ChatRoomBulkDeleteTestCase(unittest.TestCase):
    # 指定されたルームすべての所有権がユーザーにある場合、該当履歴とルーム自体が一括削除されコミットされることを検証します。
    # Verify that all target history and rooms are deleted and committed when ownership validation succeeds for all of them.
    def test_delete_rooms_for_user_deletes_history_and_rooms_after_owner_validation(self):
        connection = FakeConnection([("room-1", 7), ("room-2", 7)])

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

    # 削除対象の一部が存在しないルームの場合、削除処理全体が実行されずロールバックされることを検証します。
    # Verify that the entire deletion is canceled and rolled back if any requested room is missing.
    def test_delete_rooms_for_user_rejects_missing_room_without_delete(self):
        connection = FakeConnection([("room-1", 7)])

        # 存在しないルームを含む削除処理
        # Run bulk delete including a non-existent room ID
        with patch("blueprints.chat.rooms.get_db_connection", return_value=connection):
            with self.assertRaises(ApiServiceError) as exc_info:
                _delete_rooms_for_user(["room-1", "missing-room"], 7)

        self.assertEqual(exc_info.exception.status_code, 404)
        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)
        self.assertEqual(len(connection.cursor_instance.executed), 1)

    # 削除対象の中に他人の所有するルームが混ざっている場合、削除処理全体が実行されずロールバックされることを検証します。
    # Verify that the entire deletion is canceled and rolled back if any requested room is owned by another user.
    def test_delete_rooms_for_user_rejects_other_users_room_without_delete(self):
        connection = FakeConnection([("room-1", 7), ("room-2", 99)])

        # 他人所有のルームIDを含む削除処理
        # Run bulk delete including a room ID owned by another user
        with patch("blueprints.chat.rooms.get_db_connection", return_value=connection):
            with self.assertRaises(ApiServiceError) as exc_info:
                _delete_rooms_for_user(["room-1", "room-2"], 7)

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)
        self.assertEqual(len(connection.cursor_instance.executed), 1)

    # 一括削除エンドポイントへのアクセスにおいて、ログイン（未認証）チェックが行われることを検証します。
    # Verify that the bulk delete endpoint requires authentication and returns 401 when the user is not logged in.
    def test_delete_chat_rooms_requires_login(self):
        request = build_request(
            method="POST",
            path="/api/delete_chat_rooms",
            json_body={"room_ids": ["room-1"]},
            session={},
        )

        with patch("blueprints.chat.rooms.cleanup_ephemeral_chats"):
            response = asyncio.run(delete_chat_rooms(request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", payload)

    # ログインユーザーが自身で所有するルームを一括削除した際、APIが削除結果のメタデータを含む200レスポンスを返すことを検証します。
    # Verify that the bulk delete endpoint returns a 200 response with deletion metadata when successful.
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
