import unittest
from unittest.mock import patch

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.chat_service import validate_room_owner


# チャットルームの所有者検証ロジックをテストするための疑似DBカーソルクラス。
# Mock database cursor class for testing chat room owner validation logic.
class FakeCursor:
    # インスタンス生成時に必要な初期状態を設定します。
    # Initialize the required instance state when the object is created.
    def __init__(self, fetchone_result):
        self.fetchone_result = fetchone_result
        self.executed = []
        self.closed = False

    # クエリを実行し、引数を記録します。
    # Execute a query and record arguments.
    def execute(self, query, params=None):
        self.executed.append((query, params))

    # モックの取得結果を返却します。
    # Return mock fetch result.
    def fetchone(self):
        return self.fetchone_result

    # カーソルを閉じます。
    # Close the cursor.
    def close(self):
        self.closed = True


# チャットルームの所有者検証ロジックをテストするための疑似DBコネクションクラス。
# Mock database connection class for testing chat room owner validation logic.
class FakeConnection:
    # インスタンス生成時に必要な初期状態を設定します。
    # Initialize the required instance state when the object is created.
    def __init__(self, fetchone_result):
        self._cursor = FakeCursor(fetchone_result)
        self.closed = False

    # カーソルを返却します。
    # Return the cursor.
    def cursor(self):
        return self._cursor

    # コネクションを閉じます。
    # Close the connection.
    def close(self):
        self.closed = True

    # コンテキスト開始時に必要な準備を行います。
    # Prepare the object when entering the context.
    def __enter__(self):
        return self

    # コンテキスト終了時の後片付けを行います。
    # Clean up when leaving the context.
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


# チャットルームの所有者IDの検証ロジック（ルームが存在しない場合や他人のルームである場合のハンドリング）を検証するテストクラス。
# Test class to verify chat room owner ID validation logic (e.g. non-existent rooms or unauthorized room access).
class ChatRoomOwnerValidationTestCase(unittest.TestCase):
    # 指定されたルームが存在しない場合、ResourceNotFoundError(404)が発生することを検証します。
    # Verify that a ResourceNotFoundError (404) is raised when the requested room is missing.
    def test_validate_room_owner_raises_404_when_room_missing(self):
        fake_connection = FakeConnection(fetchone_result=None)

        # 存在しないルームに対する検証実行
        # Run owner validation on a missing room
        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with self.assertRaises(ResourceNotFoundError) as exc_info:
                validate_room_owner(
                    room_id="missing-room",
                    user_id=1,
                    forbidden_message="forbidden",
                )

        self.assertEqual(exc_info.exception.status_code, 404)
        self.assertEqual(exc_info.exception.message, "該当ルームが見つかりません")
        self.assertTrue(fake_connection._cursor.closed)
        self.assertTrue(fake_connection.closed)
        self.assertEqual(fake_connection._cursor.executed[0][1], ("missing-room",))

    # 他人のチャットルームへアクセスしようとした場合、ForbiddenOperationError(403)が発生することを検証します。
    # Verify that a ForbiddenOperationError (403) is raised when accessing another user's chat room.
    def test_validate_room_owner_raises_403_for_other_users_room(self):
        fake_connection = FakeConnection(fetchone_result=(99,))

        # 他人の所有するルームに対する検証実行
        # Run owner validation on a room owned by another user
        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with self.assertRaises(ForbiddenOperationError) as exc_info:
                validate_room_owner(
                    room_id="room-1",
                    user_id=1,
                    forbidden_message="他ユーザーのチャットルームには投稿できません",
                )

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.message, "他ユーザーのチャットルームには投稿できません")
        self.assertTrue(fake_connection._cursor.closed)
        self.assertTrue(fake_connection.closed)

    # 所有者が一致し、正当な権限がある場合に例外を投げず正常に完了することを検証します。
    # Verify that validation passes successfully (returns None) without exceptions when the owner matches.
    def test_validate_room_owner_returns_none_when_owner_matches(self):
        fake_connection = FakeConnection(fetchone_result=(1,))

        # 一致する所有者に対する検証実行
        # Run owner validation when current user owns the room
        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            result = validate_room_owner(
                room_id="room-1",
                user_id=1,
                forbidden_message="forbidden",
            )

        self.assertIsNone(result)
        self.assertTrue(fake_connection._cursor.closed)
        self.assertTrue(fake_connection.closed)


if __name__ == "__main__":
    unittest.main()
