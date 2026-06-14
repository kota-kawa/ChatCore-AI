import unittest
from unittest.mock import patch

from services.api_errors import ResourceNotFoundError
from services.memo_share import create_or_get_shared_memo_token


# 日本語: UniqueViolation に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to UniqueViolation.
class UniqueViolation(Exception):
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self):
        super().__init__("duplicate key")
        self.pgcode = "23505"


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, *, memo_exists=True, fail_attempts=None, insert_results=None):
        self.memo_exists = memo_exists
        self.fail_attempts = set(fail_attempts or [])
        self.insert_results = list(insert_results or [])
        self.insert_attempts = 0
        self.closed = False
        self._fetchone_result = None

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if normalized == "SELECT 1 FROM memo_entries WHERE id = %s AND user_id = %s":
            self._fetchone_result = (1,) if self.memo_exists else None
            return

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if "SELECT share_token, expires_at, revoked_at FROM shared_memo_entries" in normalized:
            self._fetchone_result = None
            return

        if "INSERT INTO shared_memo_entries" in normalized:
            self.insert_attempts += 1
            if self.insert_attempts in self.fail_attempts:
                raise UniqueViolation()
            token = self.insert_results.pop(0) if self.insert_results else params[1]
            self._fetchone_result = {"share_token": token, "expires_at": params[2], "revoked_at": None}
            return

        raise AssertionError(f"Unexpected query: {normalized}")

    # 日本語: fetchone に関する処理の入口です。
    # English: Entry point for logic related to fetchone.
    def fetchone(self):
        return self._fetchone_result

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


# 日本語: MemoShareTokenTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MemoShareTokenTestCase.
class MemoShareTokenTestCase(unittest.TestCase):
    # 日本語: test create or get shared memo token retries unique collision のテスト検証を担当します。
    # English: Handle verifying test behavior for test create or get shared memo token retries unique collision.
    def test_create_or_get_shared_memo_token_retries_unique_collision(self):
        fake_cursor = FakeCursor(fail_attempts={1}, insert_results=["fresh-token"])
        fake_connection = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.memo_share.Error", Exception):
            with patch("services.memo_share.get_db_connection", return_value=fake_connection):
                with patch(
                    "services.memo_share.secrets.token_urlsafe",
                    side_effect=["collision-token", "fresh-token"],
                ):
                    share_state = create_or_get_shared_memo_token(10, 20)

        self.assertEqual(share_state["share_token"], "fresh-token")
        self.assertTrue(share_state["is_active"])
        self.assertFalse(share_state["is_reused"])
        self.assertEqual(fake_cursor.insert_attempts, 2)
        self.assertEqual(fake_connection.rollback_calls, 1)
        self.assertEqual(fake_connection.commit_calls, 1)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)

    # 日本語: test create or get shared memo token raises after collision retry limit のテスト検証を担当します。
    # English: Handle verifying test behavior for test create or get shared memo token raises after collision retry limit.
    def test_create_or_get_shared_memo_token_raises_after_collision_retry_limit(self):
        fake_cursor = FakeCursor(fail_attempts={1, 2, 3, 4, 5})
        fake_connection = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test create or get shared memo token raises not found for missing memo のテスト検証を担当します。
    # English: Handle verifying test behavior for test create or get shared memo token raises not found for missing memo.
    def test_create_or_get_shared_memo_token_raises_not_found_for_missing_memo(self):
        fake_cursor = FakeCursor(memo_exists=False)
        fake_connection = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.memo_share.get_db_connection", return_value=fake_connection):
            with self.assertRaises(ResourceNotFoundError):
                create_or_get_shared_memo_token(99, 20)

        self.assertEqual(fake_connection.commit_calls, 0)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)


if __name__ == "__main__":
    unittest.main()
