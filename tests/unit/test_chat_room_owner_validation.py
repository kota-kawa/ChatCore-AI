import unittest
from unittest.mock import patch

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.chat_service import validate_room_owner


class FakeCursor:
    def __init__(self, fetchone_result):
        self.fetchone_result = fetchone_result
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self.fetchone_result

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, fetchone_result):
        self._cursor = FakeCursor(fetchone_result)
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class ChatRoomOwnerValidationTestCase(unittest.TestCase):
    def test_validate_room_owner_raises_404_when_room_missing(self):
        fake_connection = FakeConnection(fetchone_result=None)
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

    def test_validate_room_owner_raises_403_for_other_users_room(self):
        fake_connection = FakeConnection(fetchone_result=(99,))
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

    def test_validate_room_owner_returns_none_when_owner_matches(self):
        fake_connection = FakeConnection(fetchone_result=(1,))
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
