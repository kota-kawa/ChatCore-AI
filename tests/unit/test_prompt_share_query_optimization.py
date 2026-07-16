import unittest
from datetime import datetime
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import (
    _decode_prompt_feed_cursor,
    _get_prompts_with_flags,
    _get_recommended_prompts,
)


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
    # 一覧が対象ページを先に絞り、その行だけに付加情報を取得することを検証します。
    # Verify that the feed selects its page before attaching metadata.
    def test_get_prompts_with_flags_uses_page_first_query(self):
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
            payload = _get_prompts_with_flags(7)

        # クエリが一度だけ実行されたことを検証
        # Verify that only a single query was executed
        self.assertEqual(len(fake_cursor.executed), 1)
        query, params = fake_cursor.executed[0]
        
        # CTEでページを確定し、相関サブクエリで付加状態を取得することを検証
        # Verify the page-first CTE and correlated metadata lookups.
        self.assertIn("WITH page_prompts AS", query)
        self.assertIn("ORDER BY p.created_at DESC, p.id DESC", query)
        self.assertIn("LIMIT %s", query)
        self.assertIn("LEFT JOIN LATERAL", query)
        self.assertIn("EXISTS ( SELECT 1 FROM prompt_likes AS pl", query)
        self.assertIn("EXISTS ( SELECT 1 FROM task_with_examples AS used_tasks", query)
        self.assertIn("used_tasks.source_prompt_id = p.id", query)
        self.assertEqual(params, (25, 7, 7))
        self.assertTrue(payload["prompts"][0]["liked"])
        self.assertTrue(payload["prompts"][0]["used_in_chat"])
        self.assertFalse(payload["pagination"]["has_next"])
        self.assertIsNone(payload["pagination"]["next_cursor"])
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_conn.closed)

    def test_get_prompts_with_flags_applies_cursor_and_combined_filters(self):
        rows = [
            {
                "id": prompt_id,
                "title": f"Prompt {prompt_id}",
                "category": "business",
                "content": "Body",
                "author": "tester",
                "content_format": "prompt",
                "media_type": "image",
                "attributes": {},
                "attachments": [],
                "created_at": datetime(2026, 7, 16, 10, 0, prompt_id),
                "liked": False,
                "used_in_chat": False,
                "comment_count": 0,
            }
            for prompt_id in (9, 8, 7)
        ]
        fake_cursor = FakeCursor(rows)
        fake_conn = FakeConnection(fake_cursor)
        page_cursor = (datetime(2026, 7, 16, 11, 0, 0), 10)

        with patch("blueprints.prompt_share.prompt_share_api.get_db_connection", return_value=fake_conn):
            payload = _get_prompts_with_flags(
                7,
                limit=2,
                cursor=page_cursor,
                category="business",
                content_format="prompt",
                media_type="image",
            )

        query, params = fake_cursor.executed[0]
        self.assertIn("AND p.category = %s", query)
        self.assertIn("AND p.content_format = %s", query)
        self.assertIn("AND p.media_type = %s", query)
        self.assertIn("AND (p.created_at, p.id) < (%s, %s)", query)
        self.assertEqual(
            params,
            ("business", "prompt", "image", *page_cursor, 3, 7, 7),
        )
        self.assertEqual([prompt["id"] for prompt in payload["prompts"]], [9, 8])
        self.assertTrue(payload["pagination"]["has_next"])
        self.assertIsNotNone(payload["pagination"]["next_cursor"])
        self.assertEqual(
            _decode_prompt_feed_cursor(payload["pagination"]["next_cursor"]),
            (datetime(2026, 7, 16, 10, 0, 8), 8),
        )

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
