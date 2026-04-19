import unittest
from unittest.mock import patch

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.chat_service import create_or_get_shared_chat_token


class UniqueViolation(Exception):
    def __init__(self):
        super().__init__("duplicate key")
        self.pgcode = "23505"


class FakeCursor:
    def __init__(self, *, room_owner_id=1, insert_results=None, fail_attempts=None):
        self.room_owner_id = room_owner_id
        self.insert_results = list(insert_results or [])
        self.fail_attempts = set(fail_attempts or [])
        self.executed = []
        self.insert_attempts = 0
        self.closed = False
        self._fetchone_result = None

    def execute(self, query, params=None):
        self.executed.append((query, params))
        normalized = " ".join(query.split())

        if normalized == "SELECT user_id FROM chat_rooms WHERE id = %s":
            self._fetchone_result = None if self.room_owner_id is None else (self.room_owner_id,)
            return

        if "INSERT INTO shared_chat_rooms" in normalized:
            self.insert_attempts += 1
            if self.insert_attempts in self.fail_attempts:
                raise UniqueViolation()

            if self.insert_results:
                token = self.insert_results.pop(0)
            else:
                token = params[1]
            self._fetchone_result = (token,)
            return

        raise AssertionError(f"Unexpected query: {normalized}")

    def fetchone(self):
        return self._fetchone_result

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False
        self.commit_calls = 0
        self.rollback_calls = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class ChatServiceSharedTokenTestCase(unittest.TestCase):
    def test_create_or_get_shared_chat_token_raises_404_when_room_missing(self):
        fake_cursor = FakeCursor(room_owner_id=None)
        fake_connection = FakeConnection(fake_cursor)

        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with self.assertRaises(ResourceNotFoundError) as exc_info:
                create_or_get_shared_chat_token("missing-room", 10)

        self.assertEqual(exc_info.exception.status_code, 404)
        self.assertEqual(exc_info.exception.message, "該当ルームが見つかりません")
        self.assertEqual(fake_connection.commit_calls, 0)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)

    def test_create_or_get_shared_chat_token_raises_403_when_room_is_not_owned(self):
        fake_cursor = FakeCursor(room_owner_id=99)
        fake_connection = FakeConnection(fake_cursor)

        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with self.assertRaises(ForbiddenOperationError) as exc_info:
                create_or_get_shared_chat_token("room-1", 10)

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.message, "他ユーザーのチャットルームは共有できません")
        self.assertEqual(fake_connection.commit_calls, 0)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)

    def test_create_or_get_shared_chat_token_uses_on_conflict_and_reuses_existing_token(self):
        fake_cursor = FakeCursor(room_owner_id=3, insert_results=["existing-share-token"])
        fake_connection = FakeConnection(fake_cursor)

        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with patch("services.chat_service.secrets.token_urlsafe", return_value="new-token"):
                token = create_or_get_shared_chat_token("room-1", 3)

        self.assertEqual(token, "existing-share-token")
        self.assertEqual(fake_connection.commit_calls, 1)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertEqual(len(fake_cursor.executed), 2)
        self.assertIn("ON CONFLICT (chat_room_id)", fake_cursor.executed[1][0])
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)

    def test_create_or_get_shared_chat_token_retries_on_unique_token_collision(self):
        fake_cursor = FakeCursor(
            room_owner_id=5,
            insert_results=["fresh-token"],
            fail_attempts={1},
        )
        fake_connection = FakeConnection(fake_cursor)

        with patch("services.chat_service.get_db_connection", return_value=fake_connection):
            with patch(
                "services.chat_service.secrets.token_urlsafe",
                side_effect=["colliding-token", "fresh-token"],
            ):
                token = create_or_get_shared_chat_token("room-1", 5)

        self.assertEqual(token, "fresh-token")
        self.assertEqual(fake_cursor.insert_attempts, 2)
        self.assertEqual(fake_connection.rollback_calls, 1)
        self.assertEqual(fake_connection.commit_calls, 1)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)


if __name__ == "__main__":
    unittest.main()
