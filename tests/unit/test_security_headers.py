import asyncio
import unittest

import httpx
from fastapi import FastAPI, Response

from services.security_headers import CONTENT_SECURITY_POLICY, SecurityHeadersMiddleware


# 日本語: SecurityHeadersMiddlewareTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to SecurityHeadersMiddlewareTestCase.
class SecurityHeadersMiddlewareTestCase(unittest.TestCase):
    # 日本語: test adds csp and frame protection headers のテスト検証を担当します。
    # English: Handle verifying test behavior for test adds csp and frame protection headers.
    def test_adds_csp_and_frame_protection_headers(self):
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        # 日本語: ping に関する処理の入口です。
        # English: Entry point for logic related to ping.
        @app.get("/ping")
        async def ping():
            return {"status": "ok"}

        # 日本語: scenario に関する処理の入口です。
        # English: Entry point for logic related to scenario.
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                return await client.get("/ping")

        response = asyncio.run(scenario())

        self.assertEqual(response.headers["content-security-policy"], CONTENT_SECURITY_POLICY)
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["referrer-policy"], "strict-origin-when-cross-origin")

    # 日本語: test preserves existing content security policy のテスト検証を担当します。
    # English: Handle verifying test behavior for test preserves existing content security policy.
    def test_preserves_existing_content_security_policy(self):
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        # 日本語: custom に関する処理の入口です。
        # English: Entry point for logic related to custom.
        @app.get("/custom")
        async def custom():
            return Response(
                "ok",
                headers={"Content-Security-Policy": "frame-ancestors 'self'"},
            )

        # 日本語: scenario に関する処理の入口です。
        # English: Entry point for logic related to scenario.
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                return await client.get("/custom")

        response = asyncio.run(scenario())

        self.assertEqual(response.headers["content-security-policy"], "frame-ancestors 'self'")
        self.assertEqual(response.headers["x-frame-options"], "DENY")


if __name__ == "__main__":
    unittest.main()
