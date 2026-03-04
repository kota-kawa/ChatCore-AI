import unittest

from fastapi.testclient import TestClient

from blueprints.memo import memo_bp
from tests.helpers.app_helpers import build_session_test_app


class CsrfProtectionTestCase(unittest.TestCase):
    def setUp(self):
        app = build_session_test_app(memo_bp, include_test_session_route=True)
        self.client = TestClient(app)

    def test_post_rejects_when_csrf_header_missing(self):
        response = self.client.post(
            "/memo/api",
            json={"input_content": "x", "ai_response": "y", "title": "", "tags": ""},
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("CSRF", response.json().get("detail", ""))

    def test_post_rejects_when_csrf_header_mismatched(self):
        self.client.post("/_test/session", json={"csrf_token": "expected-token"})

        response = self.client.post(
            "/memo/api",
            json={"input_content": "x", "ai_response": "y", "title": "", "tags": ""},
            headers={"X-CSRF-Token": "wrong-token"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get("detail"), "CSRF token mismatch")


if __name__ == "__main__":
    unittest.main()
