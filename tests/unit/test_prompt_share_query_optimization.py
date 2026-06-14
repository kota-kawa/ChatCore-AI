import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import _get_prompts_with_flags


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
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

    # 日本語: fetchall に関する処理の入口です。
    # English: Entry point for logic related to fetchall.
    def fetchall(self):
        return self.rows

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
        self.closed = False

    # 日本語: cursor に関する処理の入口です。
    # English: Entry point for logic related to cursor.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: PromptShareQueryOptimizationTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptShareQueryOptimizationTestCase.
class PromptShareQueryOptimizationTestCase(unittest.TestCase):
    # 日本語: test get prompts with flags uses single join query のテスト検証を担当します。
    # English: Handle verifying test behavior for test get prompts with flags uses single join query.
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

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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
