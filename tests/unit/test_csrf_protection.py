import asyncio
import unittest

import httpx

from blueprints.memo import memo_bp
from tests.helpers.app_helpers import build_session_test_app


# 日本語: CSRF保護ミドルウェアの動作をテストするクラス。
# English: Test class for validating CSRF protection middleware behavior.
class CsrfProtectionTestCase(unittest.TestCase):
    # 日本語: 各テストの前にmemoブループリントを持つテスト用アプリを構築します。
    # English: Set up a test app with the memo blueprint before each test.
    def setUp(self):
        self.app = build_session_test_app(memo_bp, include_test_session_route=True)

    # 日本語: テスト用のHTTPXアシンククライアントを作成します。
    # English: Create an HTTPX async client for testing.
    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    # 日本語: CSRFヘッダーが存在しない場合に、POSTリクエストが403で拒否されることを検証します。
    # English: Verify that POST requests without a CSRF header are rejected with 403.
    def test_post_rejects_when_csrf_header_missing(self):
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                # 日本語: CSRFヘッダーなしでPOSTリクエストを送信
                # English: Send POST request without CSRF header
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

    # 日本語: CSRFヘッダーの値がセッションのトークンと一致しない場合に、POSTリクエストが403で拒否されることを検証します。
    # English: Verify that POST requests with a mismatched CSRF header are rejected with 403.
    def test_post_rejects_when_csrf_header_mismatched(self):
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                # 日本語: セッションに正しいCSRFトークンを設定した上で、異なるトークンをヘッダーに送信
                # English: Set a valid CSRF token in session, then send a different token in the header
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
