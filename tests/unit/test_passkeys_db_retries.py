import unittest
from unittest.mock import patch

from services.passkeys import update_passkey_usage


# 日本語: RetryableDeadlockError として扱う例外情報を表します。
# English: Represent exception details handled as RetryableDeadlockError.
class RetryableDeadlockError(Exception):
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self):
        super().__init__("deadlock detected")
        self.pgcode = "40P01"


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, *, fail_attempts=None):
        self.fail_attempts = set(fail_attempts or [])
        self.execute_calls = 0
        self.closed = False

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        self.execute_calls += 1
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self.execute_calls in self.fail_attempts:
            raise RetryableDeadlockError()

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: FakeConnection に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeConnection.
class FakeConnection:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

    # 日本語: cursor に関する処理の入口です。
    # English: Entry point for logic related to cursor.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # 日本語: commit に関する処理の入口です。
    # English: Entry point for logic related to commit.
    def commit(self):
        self.commit_calls += 1

    # 日本語: rollback に関する処理の入口です。
    # English: Entry point for logic related to rollback.
    def rollback(self):
        self.rollback_calls += 1

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


# 日本語: PasskeyDbRetryTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PasskeyDbRetryTestCase.
class PasskeyDbRetryTestCase(unittest.TestCase):
    # 日本語: test update passkey usage retries retryable deadlock のテスト検証を担当します。
    # English: Handle verifying test behavior for test update passkey usage retries retryable deadlock.
    def test_update_passkey_usage_retries_retryable_deadlock(self):
        fake_cursor = FakeCursor(fail_attempts={1})
        fake_connection = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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
