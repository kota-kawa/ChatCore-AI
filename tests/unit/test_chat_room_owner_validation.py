import unittest
from unittest.mock import patch

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.chat_service import validate_room_owner


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, fetchone_result):
        self.fetchone_result = fetchone_result
        self.executed = []
        self.closed = False

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        self.executed.append((query, params))

    # 日本語: fetchone に関する処理の入口です。
    # English: Entry point for logic related to fetchone.
    def fetchone(self):
        return self.fetchone_result

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: FakeConnection に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeConnection.
class FakeConnection:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, fetchone_result):
        self._cursor = FakeCursor(fetchone_result)
        self.closed = False

    # 日本語: cursor に関する処理の入口です。
    # English: Entry point for logic related to cursor.
    def cursor(self):
        return self._cursor

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True

    # 日本語: コンテキスト開始時に必要な準備を行います。
    # English: Prepare the object when entering the context.
    def __enter__(self):
        return self

    # 日本語: コンテキスト終了時の後片付けを行います。
    # English: Clean up when leaving the context.
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


# 日本語: ChatRoomOwnerValidationTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatRoomOwnerValidationTestCase.
class ChatRoomOwnerValidationTestCase(unittest.TestCase):
    # 日本語: test validate room owner raises 404 when room missing のテスト検証を担当します。
    # English: Handle verifying test behavior for test validate room owner raises 404 when room missing.
    def test_validate_room_owner_raises_404_when_room_missing(self):
        fake_connection = FakeConnection(fetchone_result=None)
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test validate room owner raises 403 for other users room のテスト検証を担当します。
    # English: Handle verifying test behavior for test validate room owner raises 403 for other users room.
    def test_validate_room_owner_raises_403_for_other_users_room(self):
        fake_connection = FakeConnection(fetchone_result=(99,))
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test validate room owner returns none when owner matches のテスト検証を担当します。
    # English: Handle verifying test behavior for test validate room owner returns none when owner matches.
    def test_validate_room_owner_returns_none_when_owner_matches(self):
        fake_connection = FakeConnection(fetchone_result=(1,))
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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
