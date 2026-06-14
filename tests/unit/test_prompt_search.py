import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_search import _search_public_prompts


# 日本語: FakeCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeCursor.
class FakeCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self):
        self.executed = []
        self.closed = False
        self._fetchone_result = None
        self._fetchall_result = []

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if "SELECT COUNT(*) AS total" in normalized:
            self._fetchone_result = {"total": 55}
            return
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if "FROM prompts" in normalized and "LIMIT %s OFFSET %s" in normalized:
            self._fetchall_result = [
                {
                    "id": 11,
                    "title": "sample",
                    "category": "仕事",
                    "content": "body",
                    "author": "tester",
                    "input_examples": "",
                    "output_examples": "",
                    "prompt_type": "text",
                    "reference_image_url": None,
                    "skill_markdown": "",
                    "skill_python_script": "",
                    "created_at": "2024-01-01T00:00:00",
                    "liked": True,
                    "bookmarked": False,
                    "saved_to_list": True,
                }
            ]

    # 日本語: fetchone に関する処理の入口です。
    # English: Entry point for logic related to fetchone.
    def fetchone(self):
        result = self._fetchone_result
        self._fetchone_result = None
        return result

    # 日本語: fetchall に関する処理の入口です。
    # English: Entry point for logic related to fetchall.
    def fetchall(self):
        result = self._fetchall_result
        self._fetchall_result = []
        return result

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


# 日本語: PromptSearchTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to PromptSearchTestCase.
class PromptSearchTestCase(unittest.TestCase):
    # 日本語: test search public prompts applies limit offset and returns metadata のテスト検証を担当します。
    # English: Handle verifying test behavior for test search public prompts applies limit offset and returns metadata.
    def test_search_public_prompts_applies_limit_offset_and_returns_metadata(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.prompt_share.prompt_search.get_db_connection", return_value=fake_conn):
            payload = _search_public_prompts("sample", 2, 20, 9)

        self.assertEqual(payload["prompts"][0]["id"], 11)
        self.assertTrue(payload["prompts"][0]["liked"])
        self.assertFalse(payload["prompts"][0]["bookmarked"])
        self.assertTrue(payload["prompts"][0]["saved_to_list"])
        self.assertEqual(payload["prompts"][0]["skill_markdown"], "")
        self.assertEqual(payload["pagination"]["page"], 2)
        self.assertEqual(payload["pagination"]["per_page"], 20)
        self.assertEqual(payload["pagination"]["total"], 55)
        self.assertEqual(payload["pagination"]["total_pages"], 3)
        self.assertTrue(payload["pagination"]["has_next"])
        self.assertTrue(payload["pagination"]["has_prev"])

        count_query, count_params = fake_cursor.executed[0]
        self.assertIn("SELECT COUNT(*) AS total", count_query)
        self.assertEqual(count_params, ("%sample%", "%sample%", "%sample%", "%sample%"))

        search_query, search_params = fake_cursor.executed[1]
        self.assertIn("LEFT JOIN prompt_likes AS pl", search_query)
        self.assertIn("LEFT JOIN prompt_list_entries AS ple", search_query)
        self.assertIn("LIMIT %s OFFSET %s", search_query)
        self.assertEqual(search_params[:2], (9, 9))
        self.assertEqual(search_params[-2:], (20, 20))
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_conn.closed)

    # 日本語: test search public prompts filters by prompt type のテスト検証を担当します。
    # English: Handle verifying test behavior for test search public prompts filters by prompt type.
    def test_search_public_prompts_filters_by_prompt_type(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.prompt_share.prompt_search.get_db_connection", return_value=fake_conn):
            _search_public_prompts("sample", 1, 10, 9, "image")

        count_query, count_params = fake_cursor.executed[0]
        self.assertIn("COALESCE(prompt_type, 'text') = %s", count_query)
        self.assertEqual(count_params, ("image", "%sample%", "%sample%", "%sample%", "%sample%"))

        search_query, search_params = fake_cursor.executed[1]
        self.assertIn("COALESCE(p.prompt_type, 'text') = %s", search_query)
        self.assertEqual(search_params[:3], (9, 9, "image"))
        self.assertEqual(search_params[-2:], (10, 0))

    # 日本語: test search public prompts returns empty payload when query is blank のテスト検証を担当します。
    # English: Handle verifying test behavior for test search public prompts returns empty payload when query is blank.
    def test_search_public_prompts_returns_empty_payload_when_query_is_blank(self):
        payload = _search_public_prompts("", 1, 20)

        self.assertEqual(payload["prompts"], [])
        self.assertEqual(payload["pagination"]["total"], 0)
        self.assertFalse(payload["pagination"]["has_next"])


if __name__ == "__main__":
    unittest.main()
