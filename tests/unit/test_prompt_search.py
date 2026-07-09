import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_search import _search_public_prompts


# テスト用の疑似DBカーソルクラス。
# Mock database cursor class for testing.
class FakeCursor:
    # 状態を記録する変数を初期化します。
    # Initialize variables to track execution state.
    def __init__(self, rows=None):
        self.executed = []
        self.closed = False
        self._fetchone_result = None
        self._fetchall_result = []
        self._rows = rows

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
            self._fetchall_result = self._rows if self._rows is not None else [
                {
                    "id": 11,
                    "title": "sample",
                    "category": "business",
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
                    "used_in_chat": True,
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
        self.assertTrue(payload["prompts"][0]["used_in_chat"])
        self.assertNotIn("bookmarked", payload["prompts"][0])
        self.assertNotIn("saved_to_list", payload["prompts"][0])
        self.assertEqual(payload["prompts"][0]["skill_markdown"], "")
        self.assertEqual(payload["pagination"]["page"], 2)
        self.assertEqual(payload["pagination"]["per_page"], 20)
        self.assertEqual(payload["pagination"]["total"], 55)
        self.assertEqual(payload["pagination"]["total_pages"], 3)
        self.assertTrue(payload["pagination"]["has_next"])
        self.assertTrue(payload["pagination"]["has_prev"])

        # 件数取得クエリとそのパラメータの妥当性を検証
        # Verify validation of count query and its parameter list
        # カテゴリはキー保存のため、ラベルに一致しない検索語では空のキー配列が渡される
        # Categories are stored as keys, so a query matching no label passes an empty key array
        count_query, count_params = fake_cursor.executed[0]
        self.assertIn("SELECT COUNT(*) AS total", count_query)
        self.assertEqual(count_params, ("%sample%", "%sample%", [], "%sample%", "%sample%"))

        # 本文検索クエリの各種条件とLIMIT / OFFSET指定を検証
        # Verify search query conditions and LIMIT / OFFSET values
        search_query, search_params = fake_cursor.executed[1]
        self.assertIn("WITH matched_prompts AS", search_query)
        self.assertIn("LEFT JOIN LATERAL", search_query)
        self.assertIn("EXISTS ( SELECT 1 FROM prompt_likes AS pl", search_query)
        self.assertIn("EXISTS ( SELECT 1 FROM task_with_examples AS used_tasks", search_query)
        self.assertIn("used_tasks.source_prompt_id = p.id", search_query)
        self.assertNotIn("GROUP BY prompt_id", search_query)
        self.assertNotIn("LEFT JOIN prompt_list_entries AS ple", search_query)
        self.assertIn("LIMIT %s OFFSET %s", search_query)
        self.assertEqual(search_params[:5], ("%sample%", "%sample%", [], "%sample%", "%sample%"))
        self.assertEqual(search_params[-4:-2], (21, 20))
        self.assertEqual(search_params[-2:], (9, 9))
        self.assertTrue(fake_cursor.closed)
        self.assertTrue(fake_conn.closed)

    # 旧プロンプト種別（prompt_type）が2軸条件に変換され、SQL条件に正しく反映されることを検証します。
    # Verify that legacy prompt_type filters are converted to two-axis SQL conditions.
    def test_search_public_prompts_maps_legacy_prompt_type_to_axes(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        # プロンプト種別を指定して検索関数を実行
        # Call search function specifying a legacy prompt type
        with patch("blueprints.prompt_share.prompt_search.get_db_connection", return_value=fake_conn):
            _search_public_prompts("sample", 1, 10, 9, "image")

        # 件数カウント用のクエリ条件に2軸条件が含まれ、パラメータが設定されているか検証
        # Verify that two-axis conditions are in the count query and parameters are set
        count_query, count_params = fake_cursor.executed[0]
        self.assertIn("AND content_format = %s", count_query)
        self.assertIn("AND media_type = %s", count_query)
        self.assertEqual(count_params, ("prompt", "image", "%sample%", "%sample%", [], "%sample%", "%sample%"))

        # データ取得用の検索クエリ条件とパラメータを検証
        # Verify data retrieval query conditions and parameters
        search_query, search_params = fake_cursor.executed[1]
        self.assertIn("AND p.content_format = %s", search_query)
        self.assertIn("AND p.media_type = %s", search_query)
        self.assertEqual(search_params[:7], ("prompt", "image", "%sample%", "%sample%", [], "%sample%", "%sample%"))
        self.assertEqual(search_params[-4:-2], (11, 0))
        self.assertEqual(search_params[-2:], (9, 9))

    # content_format / media_type の2軸フィルタがSQL条件として直接使われることを検証します。
    # Verify direct content_format/media_type filters are applied as SQL axis conditions.
    def test_search_public_prompts_filters_by_two_axes(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        with patch("blueprints.prompt_share.prompt_search.get_db_connection", return_value=fake_conn):
            _search_public_prompts(
                "sample",
                1,
                10,
                9,
                content_format="skill",
                media_type="text",
            )

        count_query, count_params = fake_cursor.executed[0]
        self.assertIn("AND content_format = %s", count_query)
        self.assertIn("AND media_type = %s", count_query)
        self.assertEqual(count_params, ("skill", "text", "%sample%", "%sample%", [], "%sample%", "%sample%"))

        search_query, search_params = fake_cursor.executed[1]
        self.assertIn("AND p.content_format = %s", search_query)
        self.assertIn("AND p.media_type = %s", search_query)
        self.assertEqual(search_params[:7], ("skill", "text", "%sample%", "%sample%", [], "%sample%", "%sample%"))
        self.assertEqual(search_params[-4:-2], (11, 0))
        self.assertEqual(search_params[-2:], (9, 9))

    # 日本語ラベルでの検索語が、DBに保存されたカテゴリキーの集合へ解決されることを検証します。
    # Verify that a Japanese label query resolves to the category keys stored in the DB.
    def test_search_public_prompts_resolves_category_label_to_keys(self):
        fake_cursor = FakeCursor()
        fake_conn = FakeConnection(fake_cursor)

        with patch("blueprints.prompt_share.prompt_search.get_db_connection", return_value=fake_conn):
            _search_public_prompts("プログラミング", 1, 10, 9)

        # カテゴリ条件はLIKEではなく、キー配列との等値照合になっている
        # The category condition is an equality match against a key array, not a LIKE
        count_query, count_params = fake_cursor.executed[0]
        self.assertIn("p.category = ANY(%s::text[])", count_query)
        self.assertEqual(count_params[2], ["coding"])

        search_query, search_params = fake_cursor.executed[1]
        self.assertIn("p.category = ANY(%s::text[])", search_query)
        self.assertEqual(search_params[2], ["coding"])

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

    # 追加ページでは全件COUNTを実行せず、LIMIT + 1で次ページ有無を判定することを検証します。
    # Verify later pages avoid COUNT and use the extra fetched row for pagination.
    def test_search_public_prompts_skips_count_for_later_pages(self):
        fake_cursor = FakeCursor(rows=[
            {
                "id": index,
                "title": f"sample-{index}",
                "category": "business",
                "content": "body",
                "author": "tester",
                "input_examples": "",
                "output_examples": "",
                "content_format": "prompt",
                "media_type": "text",
                "created_at": "2024-01-01T00:00:00",
                "liked": False,
                "used_in_chat": False,
            }
            for index in range(11)
        ])
        fake_conn = FakeConnection(fake_cursor)

        with patch("blueprints.prompt_share.prompt_search.get_db_connection", return_value=fake_conn):
            payload = _search_public_prompts("sample", 2, 10, 9, include_total=False)

        self.assertEqual(len(fake_cursor.executed), 1)
        self.assertIsNone(payload["pagination"]["total"])
        self.assertTrue(payload["pagination"]["has_next"])
        self.assertEqual(len(payload["prompts"]), 10)


if __name__ == "__main__":
    unittest.main()
