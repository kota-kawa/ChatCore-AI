import unittest
from unittest.mock import patch

from services.passkeys import update_passkey_usage


# 日本語: PostgreSQLのデッドロックエラー（pgcode: 40P01）を模擬するテスト用例外クラス。
# English: Test exception class simulating a PostgreSQL deadlock error (pgcode: 40P01).
class RetryableDeadlockError(Exception):
    # 日本語: デッドロックを示すpgcodeを付与して初期化します。
    # English: Initialize with the pgcode that indicates a deadlock condition.
    def __init__(self):
        super().__init__("deadlock detected")
        self.pgcode = "40P01"


# 日本語: テスト用のフェイクDBカーソルクラス。指定した試行回数でデッドロックエラーを発生させます。
# English: Fake DB cursor for testing. Raises a deadlock error at specified execution attempts.
class FakeCursor:
    # 日本語: 失敗させる試行番号セットと実行回数カウンターを初期化します。
    # English: Initialize with the set of attempt numbers to fail on and an execution counter.
    def __init__(self, *, fail_attempts=None):
        self.fail_attempts = set(fail_attempts or [])
        self.execute_calls = 0
        self.closed = False

    # 日本語: 実行回数をカウントし、指定された試行回数ではデッドロックエラーを発生させます。
    # English: Count execution calls and raise a deadlock error on specified attempts.
    def execute(self, query, params=None):
        self.execute_calls += 1
        if self.execute_calls in self.fail_attempts:
            raise RetryableDeadlockError()

    # 日本語: カーソルをクローズ済みとしてマークします。
    # English: Mark the cursor as closed.
    def close(self):
        self.closed = True


# 日本語: テスト用のフェイクDBコネクションクラス。コミット・ロールバック・クローズの呼び出し回数を追跡します。
# English: Fake DB connection for testing. Tracks the number of commit, rollback, and close calls.
class FakeConnection:
    # 日本語: カーソルを受け取り、各操作の呼び出しカウンターを初期化します。
    # English: Accept a cursor and initialize call counters for each operation.
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

    # 日本語: フェイクカーソルを返します。
    # English: Return the fake cursor.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # 日本語: コミット呼び出し回数をカウントします。
    # English: Count the number of commit calls.
    def commit(self):
        self.commit_calls += 1

    # 日本語: ロールバック呼び出し回数をカウントします。
    # English: Count the number of rollback calls.
    def rollback(self):
        self.rollback_calls += 1

    # 日本語: クローズ済みフラグを立てます。
    # English: Mark the connection as closed.
    def close(self):
        self.closed = True

    # 日本語: コンテキストマネージャ開始時に自身を返します。
    # English: Return self when entering a context manager block.
    def __enter__(self):
        return self

    # 日本語: コンテキストマネージャ終了時にコネクションをクローズします。
    # English: Close the connection when exiting a context manager block.
    def __exit__(self, _exc_type, _exc, _tb):
        self.close()
        return False


# 日本語: パスキー更新時のDBリトライロジック（デッドロック発生時の自動リトライ）をテストするクラス。
# English: Test class for DB retry logic in passkey updates (auto-retry on deadlock).
class PasskeyDbRetryTestCase(unittest.TestCase):
    # 日本語: デッドロックエラーが発生した場合に、パスキー更新処理が自動的にリトライされることを検証します。
    # English: Verify that update_passkey_usage automatically retries when a retryable deadlock error occurs.
    def test_update_passkey_usage_retries_retryable_deadlock(self):
        # 日本語: 1回目の実行でデッドロックを起こすフェイクカーソルを準備
        # English: Prepare a fake cursor that raises a deadlock on the 1st execution
        fake_cursor = FakeCursor(fail_attempts={1})
        fake_connection = FakeConnection(fake_cursor)

        # 日本語: DB接続・エラークラス・スリープをモック化してリトライを有効にする
        # English: Mock DB connection, error class, and sleep to enable retry behavior
        with patch("services.passkeys.Error", Exception):
            with patch("services.passkeys.get_db_connection", return_value=fake_connection):
                with patch("services.passkeys.time.sleep"):
                    update_passkey_usage(
                        123,
                        9,
                        credential_backed_up=True,
                        credential_device_type="multiDevice",
                    )

        # 日本語: 2回実行（1回失敗＋1回成功）、ロールバック1回、コミット1回であることを確認
        # English: Confirm 2 executions (1 fail + 1 success), 1 rollback, and 1 commit
        self.assertEqual(fake_cursor.execute_calls, 2)
        self.assertEqual(fake_connection.rollback_calls, 1)
        self.assertEqual(fake_connection.commit_calls, 1)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)


if __name__ == "__main__":
    unittest.main()
