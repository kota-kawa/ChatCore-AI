import unittest
from unittest.mock import patch

from services.default_shared_prompts import (
    DEFAULT_SHARED_PROMPTS,
    ensure_default_shared_prompts,
)
from tests.helpers.db_helpers import TransactionTrackingConnection


# デフォルト共有プロンプト作成処理をテストするための疑似DBカーソルクラス。
# Mock database cursor class for testing default shared prompt insertion logic.
class FakeCursor:
    def __init__(self, *, owner_id=None, existing_prompt_titles=None):
        self.owner_id = owner_id
        self.existing_prompt_titles = set(existing_prompt_titles or [])
        self.inserted_prompts = []
        self.executed_queries = []
        self._fetchone_result = None
        self._fetchall_result = None
        self.closed = False

    # クエリを実行し、テーブルのデータ状態をシミュレートします。
    # Execute a query and simulate the database tables state.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed_queries.append((normalized, params))

        # 管理者ユーザー（所有者）IDの検索をシミュレート
        # Simulate lookup for admin user (owner) ID
        if "SELECT id FROM users WHERE email = %s" in normalized:
            self._fetchone_result = (self.owner_id,) if self.owner_id is not None else None
            return

        # 管理者ユーザーの新規作成をシミュレート
        # Simulate inserting a new admin user if not exists
        if "INSERT INTO users" in normalized and "RETURNING id" in normalized:
            self.owner_id = 999
            self._fetchone_result = (self.owner_id,)
            return

        # 既存プロンプトのタイトル重複チェックをシミュレート
        # Simulate check for existing prompt titles to avoid duplicate insertions
        if "SELECT title FROM prompts" in normalized and "title IN" in normalized:
            titles = params[1:]
            self._fetchall_result = [(title,) for title in titles if title in self.existing_prompt_titles]
            return

        # プロンプトの新規登録をシミュレート
        # Simulate inserting a new prompt
        if "INSERT INTO prompts" in normalized:
            title = params[1]
            self.inserted_prompts.append(title)
            self.existing_prompt_titles.add(title)
            self._fetchone_result = None
            return

        self._fetchone_result = None

    # 1レコードの結果を取得します。
    # Fetch a single query result.
    def fetchone(self):
        result = self._fetchone_result
        self._fetchone_result = None
        return result

    # 全ての結果を取得します。
    # Fetch all query results.
    def fetchall(self):
        result = self._fetchall_result or []
        self._fetchall_result = None
        return result

    # カーソルを閉じます。
    # Close the cursor.
    def close(self):
        self.closed = True


# システム標準のデフォルト共有プロンプトが存在しない場合に自動挿入され、存在する場合はスキップされるかをテストするクラス。
# Test class to check that default shared prompts are auto-inserted if missing, and skipped if they already exist.
class DefaultSharedPromptsTestCase(unittest.TestCase):
    # デフォルト共有プロンプトが存在しないとき、データベースに不足しているすべてのプロンプトが挿入されることを検証します。
    # Verify that all missing default shared prompts are inserted into the database when they are not present.
    def test_inserts_samples_when_they_are_missing(self):
        fake_cursor = FakeCursor()
        fake_conn = TransactionTrackingConnection(fake_cursor)

        # 挿入処理をモックされたDB接続を利用して呼び出し
        # Call the insertion function using the mocked DB connection
        with patch("services.default_shared_prompts.get_db_connection", return_value=fake_conn):
            inserted = ensure_default_shared_prompts()

        self.assertEqual(inserted, len(DEFAULT_SHARED_PROMPTS))
        self.assertTrue(fake_conn.committed)
        self.assertFalse(fake_conn.rolled_back)
        self.assertTrue(fake_conn.closed)
        self.assertTrue(fake_cursor.closed)
        self.assertEqual(len(fake_cursor.inserted_prompts), len(DEFAULT_SHARED_PROMPTS))
        self.assertIsNotNone(fake_cursor.owner_id)
        self.assertEqual(
            len([query for query, _ in fake_cursor.executed_queries if "SELECT title FROM prompts" in query]),
            1,
        )

    # すべてのデフォルト共有プロンプトが既に登録されているとき、挿入処理がスキップされることを検証します。
    # Verify that the insertion is skipped when all default shared prompts already exist in the database.
    def test_skips_when_all_samples_already_exist(self):
        existing_titles = {prompt["title"] for prompt in DEFAULT_SHARED_PROMPTS}
        fake_cursor = FakeCursor(owner_id=999, existing_prompt_titles=existing_titles)
        fake_conn = TransactionTrackingConnection(fake_cursor)

        # 挿入処理をモックされたDB接続を利用して呼び出し
        # Call the insertion function using the mocked DB connection
        with patch("services.default_shared_prompts.get_db_connection", return_value=fake_conn):
            inserted = ensure_default_shared_prompts()

        self.assertEqual(inserted, 0)
        self.assertFalse(fake_conn.committed)
        self.assertFalse(fake_conn.rolled_back)
        self.assertTrue(fake_conn.closed)
        self.assertTrue(fake_cursor.closed)
        self.assertEqual(fake_cursor.inserted_prompts, [])
        self.assertFalse(
            any("INSERT INTO users" in query for query, _ in fake_cursor.executed_queries)
        )
        self.assertEqual(
            len([query for query, _ in fake_cursor.executed_queries if "SELECT title FROM prompts" in query]),
            1,
        )


if __name__ == "__main__":
    unittest.main()
