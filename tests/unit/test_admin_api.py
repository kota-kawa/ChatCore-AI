import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.admin import views as admin_views
from services.security import hash_password
from tests.helpers.request_helpers import build_request


# 日本語: 管理画面APIテスト用のHTTPリクエストを構築します。
# English: Build an HTTP request for admin API testing.
def make_request(method="GET", path="/admin/api/dashboard", json_body=None, session=None, query_string=b""):
    return build_request(
        method=method,
        path=path,
        json_body=json_body,
        session=session,
        query_string=query_string,
    )


# 日本語: 管理画面関連のAPIエンドポイントの権限検証や入力チェックをテストするクラス。
# English: Test class to verify authorization and validation checks on admin API endpoints.
class AdminApiTestCase(unittest.TestCase):
    # 日本語: ダッシュボードAPIが管理者権限（セッション内のis_admin）を要求することを検証します。
    # English: Verify that the dashboard API requires administrator privileges (is_admin in session).
    def test_dashboard_requires_admin(self):
        request = make_request(session={})
        response = asyncio.run(admin_views.api_dashboard(request))
        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")

    # 日本語: 正しいパスワードでの管理者ログイン成功時にセッションが初期化されることを検証します。
    # English: Verify that administrator login succeeds with the correct password, initializing the session.
    def test_login_success(self):
        password = "admin-test-password"
        request = make_request(
            method="POST",
            path="/admin/api/login",
            json_body={"password": password, "next": "/admin"},
            session={},
        )
        request.scope["session_id"] = "existing-admin-session"
        # 日本語: 正しいパスワードハッシュとレート制限が消費可能な状態をモック
        # English: Mock correct password hash and rate limit allowing the login
        with patch.object(admin_views, "ADMIN_PASSWORD_HASH", hash_password(password)):
            with patch("blueprints.admin.views.consume_admin_login_limit", return_value=(True, None)):
                response = asyncio.run(admin_views.api_login(request))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertTrue(request.session["is_admin"])
        self.assertIsNone(request.scope["session_id"])
        self.assertEqual(request.scope["_session_ids_to_delete"], {"existing-admin-session"})

    # 日本語: ログイン成功時のリダイレクト先(nextパラメータ)に外部URLが指定された場合、拒否されてデフォルトURLにフォールバックされることを検証します。
    # English: Verify that external URLs in the next parameter are rejected and fall back to the default URL on login.
    def test_login_rejects_external_next_url(self):
        password = "admin-test-password"
        external_next_values = ["https://evil.com", "http://evil.com", "//evil.com"]

        # 日本語: パスワードハッシュをモックして複数の外部URLリダイレクト先をサブテストで試行
        # English: Mock password hash and run subtests for each external URL redirect target
        with patch.object(admin_views, "ADMIN_PASSWORD_HASH", hash_password(password)):
            for external_next in external_next_values:
                with self.subTest(next=external_next):
                    request = make_request(
                        method="POST",
                        path="/admin/api/login",
                        json_body={"password": password, "next": external_next},
                    )
                    with patch("blueprints.admin.views.consume_admin_login_limit", return_value=(True, None)):
                        response = asyncio.run(admin_views.api_login(request))
                    payload = json.loads(response.body.decode())
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(payload["status"], "success")
                    self.assertEqual(payload["redirect"], "http://localhost:3000/admin")

    # 日本語: 誤ったパスワードによるログイン要求が拒否されることを検証します。
    # English: Verify that login requests with incorrect passwords are rejected.
    def test_login_fails_with_wrong_password(self):
        request = make_request(
            method="POST",
            path="/admin/api/login",
            json_body={"password": "wrong-password", "next": "/admin"},
        )
        # 日本語: 管理者の正しいパスワードハッシュをモック
        # English: Mock the correct admin password hash
        with patch.object(admin_views, "ADMIN_PASSWORD_HASH", hash_password("correct-password")):
            with patch("blueprints.admin.views.consume_admin_login_limit", return_value=(True, None)):
                response = asyncio.run(admin_views.api_login(request))

        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")

    # 日本語: ログイン試行回数制限（レートリミット）超過時に429ステータスを返すことを検証します。
    # English: Verify that 429 status is returned when the login rate limit is exceeded.
    def test_login_returns_429_when_rate_limited(self):
        request = make_request(
            method="POST",
            path="/admin/api/login",
            json_body={"password": "wrong-password", "next": "/admin"},
        )

        # 日本語: レートリミットエラーが返る状況をモック
        # English: Mock rate limit exhaustion error
        with patch("blueprints.admin.views.consume_admin_login_limit", return_value=(False, "too many attempts")):
            response = asyncio.run(admin_views.api_login(request))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), "60")
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "too many attempts")

    # 日本語: ダッシュボードAPIがDBテーブル情報一覧およびプレビュー情報を正しく返すことを検証します。
    # English: Verify that the dashboard API correctly returns the list of database tables and preview information.
    def test_dashboard_returns_tables(self):
        # 日本語: テスト用のダミーカーソルクラス
        # English: Dummy cursor class for testing
        class DummyCursor:
            # 日本語: カーソルをクローズします。
            # English: Close the cursor.
            def close(self):
                return None

        # 日本語: テスト用のダミーコネクションクラス
        # English: Dummy connection class for testing
        class DummyConnection:
            # 日本語: ダミーカーソルを返却します。
            # English: Return a dummy cursor.
            def cursor(self):
                return DummyCursor()

            # 日本語: コネクションをクローズします。
            # English: Close the connection.
            def close(self):
                return None

        request = make_request(session={"is_admin": True}, query_string=b"table=users")

        # 日本語: DB接続とテーブル・列情報取得ヘルパー関数をモックしてレスポンスを検証
        # English: Mock DB connections and helper functions for tables/columns to verify response
        with patch("blueprints.admin.views.get_db_connection", return_value=DummyConnection()):
            with patch("blueprints.admin.views._fetch_tables", return_value=["users"]):
                with patch(
                    "blueprints.admin.views._fetch_table_preview",
                    return_value=(["id"], [(1,)]),
                ):
                    with patch(
                        "blueprints.admin.views._fetch_table_columns",
                        return_value=[
                            {
                                "name": "id",
                                "type": "int",
                                "nullable": False,
                                "key": "PRI",
                                "default": None,
                                "extra": "",
                            }
                        ],
                    ):
                        response = asyncio.run(admin_views.api_dashboard(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["selected_table"], "users")
        self.assertEqual(payload["column_names"], ["id"])

    # 日本語: クエリパラメータに無効または不正なテーブル名（SQLインジェクションなど）が指定された際に、処理が拒否されダッシュボードデータを安全に読み込むことを検証します。
    # English: Verify that requests with invalid/malicious table names in query parameters are rejected and load dashboard safely.
    def test_dashboard_rejects_invalid_table_query(self):
        request = make_request(session={"is_admin": True}, query_string=b"table=users;DROP TABLE users")

        # 日本語: 不正なテーブル名がフィルタリングされてNoneとしてダッシュボード読み込み関数が呼ばれることをモック
        # English: Mock the dashboard data loading function to expect None due to input filtering
        with patch("blueprints.admin.views._load_dashboard_data") as mock_load_dashboard_data:
            mock_load_dashboard_data.return_value = {
                "tables": ["users"],
                "selected_table": None,
                "column_names": [],
                "column_details": [],
                "existing_columns": [],
                "rows": [],
                "missing_selected_table": False,
            }
            response = asyncio.run(admin_views.api_dashboard(request))

        self.assertEqual(response.status_code, 200)
        mock_load_dashboard_data.assert_called_once_with(None)
        payload = json.loads(response.body.decode())
        self.assertIsNone(payload["selected_table"])

    # 日本語: テーブル作成APIでサポートされていない列制約（CHECK制約など）が含まれている場合に400エラーで拒否されることを検証します。
    # English: Verify that the table creation API rejects unsupported column constraints with a 400 error.
    def test_api_create_table_rejects_unsupported_column_sql(self):
        request = make_request(
            method="POST",
            path="/admin/api/create-table",
            json_body={
                "table_name": "sample_table",
                "columns": "id INT PRIMARY KEY, note TEXT CHECK (length(note) > 0)",
            },
            session={"is_admin": True},
        )

        # 日本語: テーブル作成の実行を防ぐためにモック
        # English: Mock table creation to prevent execution
        with patch("blueprints.admin.views._create_table_in_db") as mock_create_table:
            response = asyncio.run(admin_views.api_create_table(request))

        self.assertEqual(response.status_code, 400)
        mock_create_table.assert_not_called()
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertIn("Unsupported column constraint", payload["error"])

    # 日本語: カラム追加APIにSQLインジェクションと思われるデータ型が渡された場合に、400エラーで拒否されることを検証します。
    # English: Verify that the column addition API rejects SQL injection payloads in the data type with a 400 error.
    def test_api_add_column_rejects_sql_injection_payload(self):
        request = make_request(
            method="POST",
            path="/admin/api/add-column",
            json_body={
                "table_name": "sample_table",
                "column_name": "dangerous_column",
                "column_type": "INT) DROP TABLE users --",
            },
            session={"is_admin": True},
        )

        # 日本語: カラム追加の実行を防ぐためにモック
        # English: Mock column addition to prevent execution
        with patch("blueprints.admin.views._add_column_if_valid") as mock_add_column:
            response = asyncio.run(admin_views.api_add_column(request))

        self.assertEqual(response.status_code, 400)
        mock_add_column.assert_not_called()
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertTrue(payload["error"])


if __name__ == "__main__":
    unittest.main()
