import unittest
from unittest.mock import patch

from services.api_errors import ResourceNotFoundError
from services.memo_share import create_or_get_shared_memo_token


class UniqueViolation(Exception):
    def __init__(self):
        super().__init__("duplicate key")
        self.pgcode = "23505"


class FakeCursor:
    def __init__(self, *, memo_exists=True, fail_attempts=None, insert_results=None):
        self.memo_exists = memo_exists
        self.fail_attempts = set(fail_attempts or [])
        self.insert_results = list(insert_results or [])
        self.insert_attempts = 0
        self.closed = False
        self._fetchone_result = None

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if normalized == "SELECT 1 FROM memo_entries WHERE id = %s AND user_id = %s":
            self._fetchone_result = (1,) if self.memo_exists else None
            return

        if "INSERT INTO shared_memo_entries" in normalized:
            self.insert_attempts += 1
            if self.insert_attempts in self.fail_attempts:
                raise UniqueViolation()
            token = self.insert_results.pop(0) if self.insert_results else params[1]
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
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

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


class MemoShareTokenTestCase(unittest.TestCase):
    def test_create_or_get_shared_memo_token_retries_unique_collision(self):
        fake_cursor = FakeCursor(fail_attempts={1}, insert_results=["fresh-token"])
        fake_connection = FakeConnection(fake_cursor)

        with patch("services.memo_share.Error", Exception):
            with patch("services.memo_share.get_db_connection", return_value=fake_connection):
                with patch(
                    "services.memo_share.secrets.token_urlsafe",
                    side_effect=["collision-token", "fresh-token"],
                ):
                    token = create_or_get_shared_memo_token(10, 20)

        self.assertEqual(token, "fresh-token")
        self.assertEqual(fake_cursor.insert_attempts, 2)
        self.assertEqual(fake_connection.rollback_calls, 1)
        self.assertEqual(fake_connection.commit_calls, 1)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)

    def test_create_or_get_shared_memo_token_raises_after_collision_retry_limit(self):
        fake_cursor = FakeCursor(fail_attempts={1, 2, 3, 4, 5})
        fake_connection = FakeConnection(fake_cursor)

        with patch("services.memo_share.Error", Exception):
            with patch("services.memo_share.get_db_connection", return_value=fake_connection):
                with patch(
                    "services.memo_share.secrets.token_urlsafe",
                    side_effect=[f"token-{index}" for index in range(5)],
                ):
                    with self.assertRaises(RuntimeError):
                        create_or_get_shared_memo_token(10, 20)

        self.assertEqual(fake_cursor.insert_attempts, 5)
        self.assertEqual(fake_connection.rollback_calls, 5)
        self.assertEqual(fake_connection.commit_calls, 0)

    def test_create_or_get_shared_memo_token_raises_not_found_for_missing_memo(self):
        fake_cursor = FakeCursor(memo_exists=False)
        fake_connection = FakeConnection(fake_cursor)

        with patch("services.memo_share.get_db_connection", return_value=fake_connection):
            with self.assertRaises(ResourceNotFoundError):
                create_or_get_shared_memo_token(99, 20)

        self.assertEqual(fake_connection.commit_calls, 0)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)


if __name__ == "__main__":
    unittest.main()
