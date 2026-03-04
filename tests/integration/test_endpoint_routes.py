import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from blueprints.auth import auth_bp
from blueprints.memo import memo_bp
from services.csrf import CSRF_HEADER_NAME, CSRF_SESSION_KEY
from tests.helpers.app_helpers import build_session_test_app


def build_test_app():
    return build_session_test_app(
        auth_bp,
        memo_bp,
        secret_key="endpoint-test-secret",
        include_test_session_route=True,
    )


class EndpointRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(build_test_app())

    def _set_session(self, values):
        response = self.client.post("/_test/session", json=values)
        self.assertEqual(response.status_code, 200)

    def _post_with_csrf(self, path, *, json):
        csrf_token = "test-csrf-token"
        self._set_session({CSRF_SESSION_KEY: csrf_token})
        return self.client.post(path, json=json, headers={CSRF_HEADER_NAME: csrf_token})

    def test_current_user_endpoint_when_logged_out(self):
        response = self.client.get("/api/current_user")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"logged_in": False})

    def test_current_user_endpoint_when_logged_in(self):
        self._set_session({"user_id": 7})
        with patch(
            "blueprints.auth.get_user_by_id",
            return_value={"id": 7, "email": "user@example.com"},
        ):
            response = self.client.get("/api/current_user")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["logged_in"])
        self.assertEqual(payload["user"]["id"], 7)
        self.assertEqual(payload["user"]["email"], "user@example.com")

    def test_logout_endpoint_clears_session_and_redirects(self):
        self._set_session({"user_id": 7, "user_email": "user@example.com"})

        response = self.client.get("/logout", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["location"].endswith("/login"))

        current_user = self.client.get("/api/current_user")
        self.assertEqual(current_user.status_code, 200)
        self.assertEqual(current_user.json(), {"logged_in": False})

    def test_memo_recent_endpoint_returns_serialized_memos(self):
        sample = {
            "id": 1,
            "title": "サンプル",
            "tags": "仕事",
            "created_at": datetime(2024, 1, 1, 9, 30),
            "input_content": "input",
            "ai_response": "response",
        }

        with patch("blueprints.memo._fetch_recent_memos", return_value=[sample]):
            response = self.client.get("/memo/api/recent?limit=5")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["memos"][0]["id"], 1)
        self.assertEqual(payload["memos"][0]["created_at"], "2024-01-01 09:30")

    def test_memo_create_endpoint_validates_required_fields(self):
        response = self._post_with_csrf(
            "/memo/api", json={"input_content": "hello", "ai_response": ""}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "fail")

    def test_memo_create_endpoint_success(self):
        with patch("blueprints.memo._insert_memo", return_value=42):
            response = self._post_with_csrf(
                "/memo/api",
                json={
                    "input_content": "hello",
                    "ai_response": "ok",
                    "title": "",
                    "tags": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["memo_id"], 42)


if __name__ == "__main__":
    unittest.main()
