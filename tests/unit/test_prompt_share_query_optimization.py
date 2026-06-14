import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import _get_prompts_with_flags


# 日本語: テスト用の擬似Fake Cursorクラスです。
# English: Mock Fake Cursor class for testing.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, rows):
        self.rows = rows
        self.executed = []
        self.closed = False

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

    # 日本語: テスト用の処理の入口関数fetchallです。
# English: Entry point helper function fetchall for testing.
    def fetchall(self):
        return self.rows

    # 日本語: 後処理を実行します。
# English: Perform cleanup operations.
    def close(self):
        self.closed = True


# 日本語: テスト用の擬似Fake Connectionクラスです。
# English: Mock Fake Connection class for testing.
class FakeConnection:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    # 日本語: 後処理を実行します。
# English: Perform cleanup operations.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # 日本語: 後処理を実行します。
# English: Perform cleanup operations.
    def close(self):
        self.closed = True


# 日本語: Prompt Share Query Optimizationの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Prompt Share Query Optimization.
class PromptShareQueryOptimizationTestCase(unittest.TestCase):
    # 日本語: flagsusessinglejoinクエリを使用する場合、getpromptsことを検証します。
    # English: Verify that get prompts with flags uses single join query.
    def test_get_prompts_with_flags_uses_single_join_query(self):
        fake_cursor = FakeCursor(
            [
                {
                    "id": 1,
                    "title": "Prompt",
                    "category": "仕事",
                    "content": "Body",
                    "author": "tester",
                    "input_examples": "",
                    "output_examples": "",
                    "ai_model": "gemini",
                    "prompt_type": "text",
                    "reference_image_url": None,
                    "created_at": "2024-01-01T00:00:00",
                    "liked": True,
                    "bookmarked": True,
                    "saved_to_list": False,
                }
            ]
        )
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("blueprints.prompt_share.prompt_share_api.get_db_connection", return_value=fake_conn):
            prompts = _get_prompts_with_flags(7)

        self.assertEqual(len(fake_cursor.executed), 1)
        query, params = fake_cursor.executed[0]
        self.assertIn("LEFT JOIN prompt_likes AS pl", query)
        self.assertIn("LEFT JOIN prompt_list_entries AS ple", query)
        self.assertNotIn("LEFT JOIN task_with_examples AS b", query)
        self.assertEqual(params, (7, 7))
        self.assertTrue(prompts[0]["liked"])
        self.assertTrue(prompts[0]["bookmarked"])
        self.assertFalse(prompts[0]["saved_to_list"])
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_conn.closed)


if __name__ == "__main__":
    unittest.main()
