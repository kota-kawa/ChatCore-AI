import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_search import _search_public_prompts


# テスト用の疑似DBカーソルクラス。
# Mock database cursor class for testing.
class FakeCursor:
    # 状態を記録する変数を初期化します。
    # Initialize variables to track execution state.
    def __init__(self):
        self.executed = []
        self.closed = False
        self._fetchone_result = None
        self._fetchall_result = []

    # クエリを実行し、クエリ内容に応じたダミーの戻り値をセットします。
    # Execute a query and set dummy return values based on the query contents.
    def execute(self, query, params=None):
        # クエリ内の改行や余分なスペースを正規化して記録
        # Normalize whitespace in the query and record it with parameters
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))

        # レコードカウント取得クエリ用のダミーカウント値
        # Dummy count value for record count queries
        if "SELECT COUNT(*) AS total" in normalized:
            self._fetchone_result = {"total": 55}
            return

        # プロンプト取得クエリ用のダミープロンプト一覧
        # Dummy prompt list for prompt retrieval queries
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

    # クエリの実行結果から1レコード分を取得します。
    # Fetch a single record result.
    def fetchone(self):
        result = self._fetchone_result
        self._fetchone_result = None
        return result

    # クエリの実行結果から全レコードを取得します。
    # Fetch all record results.
    def fetchall(self):
        result = self._fetchall_result
        self._fetchall_result = []
        return result

    # カーソルを閉じます。
    # Close the cursor.
    def close(self):
        self.closed = True


# テスト用の疑似DBコネクションクラス。
# Mock database connection class for testing.
class FakeConnection:
    # 疑似コネクションを初期化します。
    # Initialize the fake connection.
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    # カーソルを返却します。
    # Return the cursor.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # コネクションを閉じます。
    # Close the connection.
    def close(self):
        self.closed = True


# 公開プロンプト検索ロジックのパラメータ指定、フィルタリング、ページネーションなどを検証するテストクラス。
# Test class to verify parameter handling, filtering, and pagination in public prompt search logic.
class PromptSearchTestCase(unittest.TestCase):
    # 検索クエリ、ページ番号、件数制限を指定したときに、適切なSQLパラメータ（LIMIT/OFFSETなど）が渡されメタデータが得られることを検証します。
    # Verify that appropriate SQL parameters (LIMIT/OFFSET) and metadata are returned when passing search parameters.
    def test_search_public_prompts_applies_limit_offset_and_returns_metadata(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        # 検索関数をモックされたDB接続を利用して呼び出し
        # Call search function with mocked DB connection
        with patch("blueprints.prompt_share.prompt_search.get_db_connection", return_value=fake_conn):
            payload = _search_public_prompts("sample", 2, 20, 9)

        # 検索結果データとメタデータが仕様通りに設定されていることを検証
        # Verify that search result data and metadata are set according to specifications
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

        # 件数取得クエリとそのパラメータの妥当性を検証
        # Verify validation of count query and its parameter list
        count_query, count_params = fake_cursor.executed[0]
        self.assertIn("SELECT COUNT(*) AS total", count_query)
        self.assertEqual(count_params, ("%sample%", "%sample%", "%sample%", "%sample%"))

        # 本文検索クエリの各種条件とLIMIT / OFFSET指定を検証
        # Verify search query conditions and LIMIT / OFFSET values
        search_query, search_params = fake_cursor.executed[1]
        self.assertIn("LEFT JOIN prompt_likes AS pl", search_query)
        self.assertIn("LEFT JOIN prompt_list_entries AS ple", search_query)
        self.assertIn("LIMIT %s OFFSET %s", search_query)
        self.assertEqual(search_params[:2], (9, 9))
        self.assertEqual(search_params[-2:], (20, 20))
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_conn.closed)

    # プロンプトの種別（prompt_type）によるフィルタリングがSQL条件に正しく反映されることを検証します。
    # Verify that filtering by prompt_type is correctly reflected in the SQL query conditions.
    def test_search_public_prompts_filters_by_prompt_type(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        # プロンプト種別を指定して検索関数を実行
        # Call search function specifying a prompt type
        with patch("blueprints.prompt_share.prompt_search.get_db_connection", return_value=fake_conn):
            _search_public_prompts("sample", 1, 10, 9, "image")

        # 件数カウント用のクエリ条件に COALESCE(prompt_type) が含まれ、パラメータが設定されているか検証
        # Verify that COALESCE(prompt_type) is in count query conditions and parameters are set
        count_query, count_params = fake_cursor.executed[0]
        self.assertIn("COALESCE(prompt_type, 'text') = %s", count_query)
        self.assertEqual(count_params, ("image", "%sample%", "%sample%", "%sample%", "%sample%"))

        # データ取得用の検索クエリ条件とパラメータを検証
        # Verify data retrieval query conditions and parameters
        search_query, search_params = fake_cursor.executed[1]
        self.assertIn("COALESCE(p.prompt_type, 'text') = %s", search_query)
        self.assertEqual(search_params[:3], (9, 9, "image"))
        self.assertEqual(search_params[-2:], (10, 0))

    # 検索クエリが空の場合に、DBにアクセスせず空の結果を即座に返すことを検証します。
    # Verify that search returns an empty payload immediately without query execution when search query is blank.
    def test_search_public_prompts_returns_empty_payload_when_query_is_blank(self):
        # 空文字のクエリを渡して検索関数を実行
        # Run search function with empty query string
        payload = _search_public_prompts("", 1, 20)

        # 空配列および件数 0 が返り、次ページが存在しないことを検証
        # Verify that empty list, 0 count are returned and no next page is available
        self.assertEqual(payload["prompts"], [])
        self.assertEqual(payload["pagination"]["total"], 0)
        self.assertFalse(payload["pagination"]["has_next"])


if __name__ == "__main__":
    unittest.main()
