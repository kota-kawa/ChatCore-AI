import asyncio
import unittest

import httpx
from fastapi import FastAPI, Response

from services.security_headers import CONTENT_SECURITY_POLICY, SecurityHeadersMiddleware


class SecurityHeadersMiddlewareTestCase(unittest.TestCase):
    def test_adds_csp_and_frame_protection_headers(self):
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/ping")
        async def ping():
            return {"status": "ok"}

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

    def test_preserves_existing_content_security_policy(self):
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/custom")
        async def custom():
            return Response(
                "ok",
                headers={"Content-Security-Policy": "frame-ancestors 'self'"},
            )

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
