import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.admin import views as admin_views
from services.security import hash_password
from tests.helpers.request_helpers import build_request


def make_request(method="GET", path="/admin/api/dashboard", json_body=None, session=None, query_string=b""):
    return build_request(
        method=method,
        path=path,
        json_body=json_body,
        session=session,
        query_string=query_string,
    )


class AdminApiTestCase(unittest.TestCase):
    def test_dashboard_requires_admin(self):
        request = make_request(session={})
        response = asyncio.run(admin_views.api_dashboard(request))
        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")

    def test_login_success(self):
        password = "admin-test-password"
        request = make_request(
            method="POST",
            path="/admin/api/login",
            json_body={"password": password, "next": "/admin"},
            session={},
        )
        request.scope["session_id"] = "existing-admin-session"
        with patch.object(admin_views, "ADMIN_PASSWORD_HASH", hash_password(password)):
            with patch("blueprints.admin.views.consume_admin_login_limit", return_value=(True, None)):
                response = asyncio.run(admin_views.api_login(request))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertTrue(request.session["is_admin"])
        self.assertIsNone(request.scope["session_id"])
        self.assertEqual(request.scope["_session_ids_to_delete"], {"existing-admin-session"})


    def test_login_rejects_external_next_url(self):
        password = "admin-test-password"
        external_next_values = ["https://evil.com", "http://evil.com", "//evil.com"]

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

    def test_login_fails_with_wrong_password(self):
        request = make_request(
            method="POST",
            path="/admin/api/login",
            json_body={"password": "wrong-password", "next": "/admin"},
        )
        with patch.object(admin_views, "ADMIN_PASSWORD_HASH", hash_password("correct-password")):
            with patch("blueprints.admin.views.consume_admin_login_limit", return_value=(True, None)):
                response = asyncio.run(admin_views.api_login(request))

        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")

    def test_login_returns_429_when_rate_limited(self):
        request = make_request(
            method="POST",
            path="/admin/api/login",
            json_body={"password": "wrong-password", "next": "/admin"},
        )

        with patch("blueprints.admin.views.consume_admin_login_limit", return_value=(False, "too many attempts")):
            response = asyncio.run(admin_views.api_login(request))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), "60")
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "too many attempts")

    def test_dashboard_returns_tables(self):
        class DummyCursor:
            def close(self):
                return None

        class DummyConnection:
            def cursor(self):
                return DummyCursor()

            def close(self):
                return None

        request = make_request(session={"is_admin": True}, query_string=b"table=users")

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

    def test_dashboard_rejects_invalid_table_query(self):
        request = make_request(session={"is_admin": True}, query_string=b"table=users;DROP TABLE users")

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

        with patch("blueprints.admin.views._create_table_in_db") as mock_create_table:
            response = asyncio.run(admin_views.api_create_table(request))

        self.assertEqual(response.status_code, 400)
        mock_create_table.assert_not_called()
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertIn("Unsupported column constraint", payload["error"])

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

        with patch("blueprints.admin.views._add_column_if_valid") as mock_add_column:
            response = asyncio.run(admin_views.api_add_column(request))

        self.assertEqual(response.status_code, 400)
        mock_add_column.assert_not_called()
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertTrue(payload["error"])


if __name__ == "__main__":
    unittest.main()
