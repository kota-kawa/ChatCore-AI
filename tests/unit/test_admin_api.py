import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.admin import views as admin_views
from services.security import hash_password
from tests.helpers.request_helpers import build_request


# 日本語: make request の生成処理を担当します。
# English: Handle creating for make request.
def make_request(method="GET", path="/admin/api/dashboard", json_body=None, session=None, query_string=b""):
    return build_request(
        method=method,
        path=path,
        json_body=json_body,
        session=session,
        query_string=query_string,
    )


# 日本語: AdminApiTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to AdminApiTestCase.
class AdminApiTestCase(unittest.TestCase):
    # 日本語: test dashboard requires admin のテスト検証を担当します。
    # English: Handle verifying test behavior for test dashboard requires admin.
    def test_dashboard_requires_admin(self):
        request = make_request(session={})
        response = asyncio.run(admin_views.api_dashboard(request))
        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")

    # 日本語: test login success のテスト検証を担当します。
    # English: Handle verifying test behavior for test login success.
    def test_login_success(self):
        password = "admin-test-password"
        request = make_request(
            method="POST",
            path="/admin/api/login",
            json_body={"password": password, "next": "/admin"},
            session={},
        )
        request.scope["session_id"] = "existing-admin-session"
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(admin_views, "ADMIN_PASSWORD_HASH", hash_password(password)):
            with patch("blueprints.admin.views.consume_admin_login_limit", return_value=(True, None)):
                response = asyncio.run(admin_views.api_login(request))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertTrue(request.session["is_admin"])
        self.assertIsNone(request.scope["session_id"])
        self.assertEqual(request.scope["_session_ids_to_delete"], {"existing-admin-session"})


    # 日本語: test login rejects external next url のテスト検証を担当します。
    # English: Handle verifying test behavior for test login rejects external next url.
    def test_login_rejects_external_next_url(self):
        password = "admin-test-password"
        external_next_values = ["https://evil.com", "http://evil.com", "//evil.com"]

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test login fails with wrong password のテスト検証を担当します。
    # English: Handle verifying test behavior for test login fails with wrong password.
    def test_login_fails_with_wrong_password(self):
        request = make_request(
            method="POST",
            path="/admin/api/login",
            json_body={"password": "wrong-password", "next": "/admin"},
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch.object(admin_views, "ADMIN_PASSWORD_HASH", hash_password("correct-password")):
            with patch("blueprints.admin.views.consume_admin_login_limit", return_value=(True, None)):
                response = asyncio.run(admin_views.api_login(request))

        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")

    # 日本語: test login returns 429 when rate limited のテスト検証を担当します。
    # English: Handle verifying test behavior for test login returns 429 when rate limited.
    def test_login_returns_429_when_rate_limited(self):
        request = make_request(
            method="POST",
            path="/admin/api/login",
            json_body={"password": "wrong-password", "next": "/admin"},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.admin.views.consume_admin_login_limit", return_value=(False, "too many attempts")):
            response = asyncio.run(admin_views.api_login(request))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), "60")
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "too many attempts")

    # 日本語: test dashboard returns tables のテスト検証を担当します。
    # English: Handle verifying test behavior for test dashboard returns tables.
    def test_dashboard_returns_tables(self):
        # 日本語: DummyCursor に関するデータや振る舞いをまとめます。
        # English: Group data and behavior related to DummyCursor.
        class DummyCursor:
            # 日本語: close に関する処理の入口です。
            # English: Entry point for logic related to close.
            def close(self):
                return None

        # 日本語: DummyConnection に関するデータや振る舞いをまとめます。
        # English: Group data and behavior related to DummyConnection.
        class DummyConnection:
            # 日本語: cursor に関する処理の入口です。
            # English: Entry point for logic related to cursor.
            def cursor(self):
                return DummyCursor()

            # 日本語: close に関する処理の入口です。
            # English: Entry point for logic related to close.
            def close(self):
                return None

        request = make_request(session={"is_admin": True}, query_string=b"table=users")

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test dashboard rejects invalid table query のテスト検証を担当します。
    # English: Handle verifying test behavior for test dashboard rejects invalid table query.
    def test_dashboard_rejects_invalid_table_query(self):
        request = make_request(session={"is_admin": True}, query_string=b"table=users;DROP TABLE users")

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test api create table rejects unsupported column sql のテスト検証を担当します。
    # English: Handle verifying test behavior for test api create table rejects unsupported column sql.
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

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.admin.views._create_table_in_db") as mock_create_table:
            response = asyncio.run(admin_views.api_create_table(request))

        self.assertEqual(response.status_code, 400)
        mock_create_table.assert_not_called()
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertIn("Unsupported column constraint", payload["error"])

    # 日本語: test api add column rejects sql injection payload のテスト検証を担当します。
    # English: Handle verifying test behavior for test api add column rejects sql injection payload.
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

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.admin.views._add_column_if_valid") as mock_add_column:
            response = asyncio.run(admin_views.api_add_column(request))

        self.assertEqual(response.status_code, 400)
        mock_add_column.assert_not_called()
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertTrue(payload["error"])


if __name__ == "__main__":
    unittest.main()
