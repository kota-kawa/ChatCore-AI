import unittest
from unittest.mock import patch

from services.api_errors import ResourceNotFoundError
from services.memo_share import create_or_get_shared_memo_token


# PostgreSQLの一意性制約エラー（エラーコード: 23505）をシミュレートする疑似例外クラス。
# Mock exception class simulating PostgreSQL's unique key violation (error code: 23505).
class UniqueViolation(Exception):
    def __init__(self):
        super().__init__("duplicate key")
        self.pgcode = "23505"


# メモ共有トークン生成ロジック（メモの存在チェック、一意性競合、挿入リトライ等）をテストするための疑似DBカーソルクラス。
# Mock database cursor class for testing shared memo token creation, collision retries, and existence checks.
class FakeCursor:
    def __init__(self, *, memo_exists=True, fail_attempts=None, insert_results=None):
        self.memo_exists = memo_exists
        self.fail_attempts = set(fail_attempts or [])
        self.insert_results = list(insert_results or [])
        self.insert_attempts = 0
        self.closed = False
        self._fetchone_result = None

    # クエリを実行し、引数および状態の変化を追跡・記録します。
    # Execute a query and track/log the database state changes.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())

        # メモの存在確認クエリのモック
        # Mocking check for memo existence and ownership
        if normalized == "SELECT 1 FROM memo_entries WHERE id = %s AND user_id = %s":
            self._fetchone_result = (1,) if self.memo_exists else None
            return

        # 既存の共有エントリ取得クエリのモック
        # Mocking retrieval of existing shared memo entry
        if "SELECT share_token, expires_at, revoked_at FROM shared_memo_entries" in normalized:
            self._fetchone_result = None
            return

        # 新規共有エントリ追加クエリのモック（一意性競合テスト用に例外スローを制御）
        # Mocking insertion of shared memo entry (raise UniqueViolation if configured)
        if "INSERT INTO shared_memo_entries" in normalized:
            self.insert_attempts += 1
            if self.insert_attempts in self.fail_attempts:
                raise UniqueViolation()
            token = self.insert_results.pop(0) if self.insert_results else params[1]
            self._fetchone_result = {"share_token": token, "expires_at": params[2], "revoked_at": None}
            return

        raise AssertionError(f"Unexpected query: {normalized}")

    # レコードの取得結果を返します。
    # Return fetch result.
    def fetchone(self):
        return self._fetchone_result

    # カーソルを閉じます。
    # Close the cursor.
    def close(self):
        self.closed = True


# メモ共有トークン生成ロジックをテストするための疑似DBコネクションクラス。
# Mock database connection class for testing shared memo token creation.
class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

    # カーソルを返却します。
    # Return the cursor.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # コミットされた回数を記録します。
    # Record commit execution count.
    def commit(self):
        self.commit_calls += 1

    # ロールバックされた回数を記録します。
    # Record rollback execution count.
    def rollback(self):
        self.rollback_calls += 1

    # コネクションを閉じます。
    # Close the connection.
    def close(self):
        self.closed = True

    # Prepare the object when entering the context.
    def __enter__(self):
        return self

    # Clean up when leaving the context.
    def __exit__(self, _exc_type, _exc, _tb):
        self.close()
        return False


# メモ共有用のURL安全トークン生成において、一意性制約違反（同一トークンの重複衝突）時のリトライやリトライ上限、およびメモが見つからない場合のエラーをテストするクラス。
# Test class to check URL-safe token generation for shared memos, including collision retries, retry limits, and missing memo errors.
class MemoShareTokenTestCase(unittest.TestCase):
    # トークン追加時に一意性競合（重複衝突）が発生した場合、新しいトークンを再生成して自動的にインサートをリトライし、成功することを検証します。
    # Verify that unique key collisions during token insertion trigger regenerating the token and retrying the operation successfully.
    def test_create_or_get_shared_memo_token_retries_unique_collision(self):
        fake_cursor = FakeCursor(fail_attempts={1}, insert_results=["fresh-token"])
        fake_connection = FakeConnection(fake_cursor)

        # モックされたDB接続を利用し、一回目に競合が発生し二回目に成功する設定で呼び出し
        # Run token generator, expecting a collision on the first try and success on the second try
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

    # 一意性競合が規定の最大リトライ回数連続して発生した場合、無限ループを防ぐため処理を中断しエラーをスローすることを検証します。
    # Verify that a RuntimeError is raised after exceeding the maximum number of token collision retries to prevent infinite loops.
    def test_create_or_get_shared_memo_token_raises_after_collision_retry_limit(self):
        fake_cursor = FakeCursor(fail_attempts={1, 2, 3, 4, 5})
        fake_connection = FakeConnection(fake_cursor)

        # すべての試行で競合が発生する設定で呼び出し
        # Run token generator with collisions occurring on all retries, expecting failure
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

    # 共有しようとしたメモIDが存在しない、または現在のユーザーの所有物でない場合に、ResourceNotFoundErrorがスローされることを検証します。
    # Verify that a ResourceNotFoundError is raised if the memo ID is missing or not owned by the requesting user.
    def test_create_or_get_shared_memo_token_raises_not_found_for_missing_memo(self):
        fake_cursor = FakeCursor(memo_exists=False)
        fake_connection = FakeConnection(fake_cursor)

        # 存在しないメモIDを指定して呼び出し
        # Run token generator for a missing memo, expecting 404 Error
        with patch("services.memo_share.get_db_connection", return_value=fake_connection):
            with self.assertRaises(ResourceNotFoundError):
                create_or_get_shared_memo_token(99, 20)

        self.assertEqual(fake_connection.commit_calls, 0)
        self.assertEqual(fake_connection.rollback_calls, 0)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_connection.closed)


if __name__ == "__main__":
    unittest.main()
