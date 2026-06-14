import asyncio
import unittest

import httpx
from fastapi import FastAPI, Response

from services.security_headers import CONTENT_SECURITY_POLICY, SecurityHeadersMiddleware


# HTTPレスポンスにContent-Security-Policy (CSP)などのセキュリティヘッダーを追加するミドルウェアの挙動をテストするクラス。
# Test class to check the behavior of the middleware that adds security headers (e.g. CSP, X-Frame-Options) to HTTP responses.
class SecurityHeadersMiddlewareTestCase(unittest.TestCase):
    # ミドルウェアによって、デフォルトのCSPやクリックジャッキング対策ヘッダー（X-Frame-Options: DENYなど）が自動付与されることを検証します。
    # Verify that default CSP and clickjacking protection headers (e.g. X-Frame-Options: DENY) are automatically added by the middleware.
    def test_adds_csp_and_frame_protection_headers(self):
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/ping")
        async def ping():
            return {"status": "ok"}

        # HTTPリクエストテスト用の非同期シナリオ
        # Async scenario to perform test HTTP requests
        async def scenario():
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

    # レスポンスにあらかじめ独自のCSPヘッダーが設定されている場合、ミドルウェアがそれを上書きせず維持することを検証します。
    # Verify that the middleware preserves any pre-existing Content-Security-Policy header set by the handler.
    def test_preserves_existing_content_security_policy(self):
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/custom")
        async def custom():
            return Response(
                "ok",
                headers={"Content-Security-Policy": "frame-ancestors 'self'"},
            )

        # HTTPリクエストテスト用の非同期シナリオ
        # Async scenario to perform test HTTP requests
        async def scenario():
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
