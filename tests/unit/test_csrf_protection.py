import asyncio
import unittest

import httpx

from blueprints.memo import memo_bp
from tests.helpers.app_helpers import build_session_test_app


class CsrfProtectionTestCase(unittest.TestCase):
    def setUp(self):
        self.app = build_session_test_app(memo_bp, include_test_session_route=True)

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    def test_post_rejects_when_csrf_header_missing(self):
        async def scenario():
            async with self._make_client() as client:
                response = await client.post(
                    "/memo/api",
                    json={
                        "input_content": "x",
                        "ai_response": "y",
                        "title": "",
                        "tags": "",
                    },
                )

            self.assertEqual(response.status_code, 403)
            self.assertIn("CSRF", response.json().get("detail", ""))

        asyncio.run(scenario())

    def test_post_rejects_when_csrf_header_mismatched(self):
        async def scenario():
            async with self._make_client() as client:
                await client.post("/_test/session", json={"csrf_token": "expected-token"})
                response = await client.post(
                    "/memo/api",
                    json={
                        "input_content": "x",
                        "ai_response": "y",
                        "title": "",
                        "tags": "",
                    },
                    headers={"X-CSRF-Token": "wrong-token"},
                )

            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json().get("detail"), "CSRF token mismatch")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
