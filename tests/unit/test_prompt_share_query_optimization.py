import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import _get_prompts_with_flags, _get_recommended_prompts


# テスト用の疑似DBカーソルクラス。
# Mock database cursor class for testing.
class FakeCursor:
    # 疑似カーソルを返却する行データで初期化します。
    # Initialize the mock cursor with rows to be returned.
    def __init__(self, rows):
        self.rows = rows
        self.executed = []
        self.closed = False

    # クエリを実行し、実行された内容を記録します。
    # Execute a query and record the query execution state.
    def execute(self, query, params=None):
        # クエリ内の余分な空白をトリミングして記録
        # Record the normalized query string and parameters
        self.executed.append((" ".join(query.split()), params))

    # 全ての行データを返却します。
    # Fetch all row results.
    def fetchall(self):
        return self.rows

    # カーソルをクローズ状態にします。
    # Close the cursor.
    def close(self):
        self.closed = True


# テスト用の疑似DBコネクションクラス。
# Mock database connection class for testing.
class FakeConnection:
    # 疑似コネクションをカーソルオブジェクトで初期化します。
    # Initialize the fake connection with a cursor instance.
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    # 疑似カーソルを取得します。
    # Return the cursor.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # コネクションをクローズ状態にします。
    # Close the connection.
    def close(self):
        self.closed = True


# クエリの最適化（フラグ情報などを一括取得する効率的なJOINクエリ）を検証するテストクラス。
# Test case class to verify query optimization (efficient JOIN queries that fetch flags together).
class PromptShareQueryOptimizationTestCase(unittest.TestCase):
    # 各種フラグ情報（いいねなど）を含むプロンプト取得時に、不要な重複クエリではなく1回のJOINクエリで取得されることを検証します。
    # Verify that get prompts with flags uses a single join query instead of multiple query executions.
    def test_get_prompts_with_flags_uses_single_join_query(self):
        # テスト対象関数から返されるダミーレコードを設定
        # Configure dummy records returned by the function under test
        fake_cursor = FakeCursor(
            [
                {
                    "id": 1,
                    "title": "Prompt",
                    "category": "business",
                    "content": "Body",
                    "author": "tester",
                    "input_examples": "",
                    "output_examples": "",
                    "ai_model": "gemini",
                    "prompt_type": "text",
                    "reference_image_url": None,
                    "created_at": "2024-01-01T00:00:00",
                    "liked": True,
                    "used_in_chat": True,
                }
            ]
        )
        fake_conn = FakeConnection(fake_cursor)

        # データベース接続をモック化してプロンプト取得処理を実行
        # Mock database connection and execute retrieval helper
        with patch("blueprints.prompt_share.prompt_share_api.get_db_connection", return_value=fake_conn):
            prompts = _get_prompts_with_flags(7)

        # クエリが一度だけ実行されたことを検証
        # Verify that only a single query was executed
        self.assertEqual(len(fake_cursor.executed), 1)
        query, params = fake_cursor.executed[0]
        
        # 必要なJOIN文が含まれ、不要なテーブルJOINがないこと、およびパラメータの妥当性を検証
        # Verify needed JOINs are present, unnecessary joins are absent, and check parameter mappings
        self.assertIn("LEFT JOIN prompt_likes AS pl", query)
        self.assertIn("LEFT JOIN task_with_examples AS used_tasks", query)
        self.assertIn("used_tasks.source_prompt_id = p.id", query)
        self.assertNotIn("LEFT JOIN prompt_list_entries AS ple", query)
        self.assertNotIn("LEFT JOIN task_with_examples AS b", query)
        self.assertEqual(params, (7, 7))
        self.assertTrue(prompts[0]["liked"])
        self.assertTrue(prompts[0]["used_in_chat"])
        self.assertNotIn("bookmarked", prompts[0])
        self.assertNotIn("saved_to_list", prompts[0])
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_conn.closed)

    # おすすめ取得では閲覧中の投稿を除外し、DB側でランダムな最大件数に絞ることを検証します。
    # Verify recommendation lookup excludes the viewed prompt and limits random rows in the database.
    def test_get_recommended_prompts_excludes_current_prompt_and_limits_results(self):
        fake_cursor = FakeCursor(
            [
                {
                    "id": 8,
                    "title": "Recommended prompt",
                    "category": "business",
                    "content": "Body",
                    "author": "tester",
                    "content_format": "prompt",
                    "media_type": "text",
                    "attributes": {},
                    "attachments": [],
                    "created_at": "2024-01-01T00:00:00",
                }
            ]
        )
        fake_conn = FakeConnection(fake_cursor)

        with patch("blueprints.prompt_share.prompt_share_api.get_db_connection", return_value=fake_conn):
            prompts = _get_recommended_prompts(exclude_prompt_id=7)

        self.assertEqual(len(fake_cursor.executed), 1)
        query, params = fake_cursor.executed[0]
        self.assertIn("COALESCE(p.id <> %s, TRUE)", query)
        self.assertIn("ORDER BY RANDOM()", query)
        self.assertIn("LIMIT %s", query)
        self.assertEqual(params, (7, 3))
        self.assertEqual(prompts[0]["id"], 8)
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_conn.closed)


if __name__ == "__main__":
    unittest.main()
