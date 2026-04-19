import unittest
from unittest.mock import patch

from services.passkeys import update_passkey_usage


class RetryableDeadlockError(Exception):
    def __init__(self):
        super().__init__("deadlock detected")
        self.pgcode = "40P01"


class FakeCursor:
    def __init__(self, *, fail_attempts=None):
        self.fail_attempts = set(fail_attempts or [])
        self.execute_calls = 0
        self.closed = False

    def execute(self, query, params=None):
        self.execute_calls += 1
        if self.execute_calls in self.fail_attempts:
            raise RetryableDeadlockError()

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

    def cursor(self, *args, **kwargs):
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


class PasskeyDbRetryTestCase(unittest.TestCase):
    def test_update_passkey_usage_retries_retryable_deadlock(self):
        fake_cursor = FakeCursor(fail_attempts={1})
        fake_connection = FakeConnection(fake_cursor)

        with patch("services.passkeys.Error", Exception):
            with patch("services.passkeys.get_db_connection", return_value=fake_connection):
                with patch("services.passkeys.time.sleep"):
                    update_passkey_usage(
                        123,
                        9,
                        credential_backed_up=True,
                        credential_device_type="multiDevice",
                    )

        self.assertEqual(fake_cursor.execute_calls, 2)
        self.assertEqual(fake_connection.rollback_calls, 1)
        self.assertEqual(fake_connection.commit_calls, 1)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)


if __name__ == "__main__":
    unittest.main()
