import asyncio
import unittest

import httpx

from blueprints.memo import memo_bp
from tests.helpers.app_helpers import build_session_test_app


# 日本語: CsrfProtectionTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to CsrfProtectionTestCase.
class CsrfProtectionTestCase(unittest.TestCase):
    # 日本語: setUp に関する処理の入口です。
    # English: Entry point for logic related to setUp.
    def setUp(self):
        self.app = build_session_test_app(memo_bp, include_test_session_route=True)

    # 日本語: make client の生成処理を担当します。
    # English: Handle creating for make client.
    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    # 日本語: test post rejects when csrf header missing のテスト検証を担当します。
    # English: Handle verifying test behavior for test post rejects when csrf header missing.
    def test_post_rejects_when_csrf_header_missing(self):
        # 日本語: scenario に関する処理の入口です。
        # English: Entry point for logic related to scenario.
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                response = await client.post(
                    "/memo/api",
                    json={
                        "ai_response": "y",
                        "title": "",
                        "tags": "",
                    },
                )

            self.assertEqual(response.status_code, 403)
            self.assertIn("CSRF", response.json().get("detail", ""))

        asyncio.run(scenario())

    # 日本語: test post rejects when csrf header mismatched のテスト検証を担当します。
    # English: Handle verifying test behavior for test post rejects when csrf header mismatched.
    def test_post_rejects_when_csrf_header_mismatched(self):
        # 日本語: scenario に関する処理の入口です。
        # English: Entry point for logic related to scenario.
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                await client.post("/_test/session", json={"csrf_token": "expected-token"})
                response = await client.post(
                    "/memo/api",
                    json={
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
