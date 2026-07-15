import asyncio
import unittest
from unittest.mock import patch

from services.mcp_request_protection import McpRequestProtectionMiddleware


def _scope(path: str, *, method: str = "POST", headers: list[tuple[bytes, bytes]] | None = None):
    return {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers or [],
        "client": ("203.0.113.10", 12345),
        "server": ("example.test", 443),
    }


async def _single_body_receive(body: bytes):
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


class McpRequestProtectionMiddlewareTestCase(unittest.TestCase):
    def test_mcp_auth_challenge_includes_required_scope(self):
        async def inner(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (
                            b"www-authenticate",
                            b'Bearer resource_metadata="https://example.test/.well-known/oauth-protected-resource/mcp"',
                        )
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})

        middleware = McpRequestProtectionMiddleware(inner, required_scope="prompts:write")
        messages = []

        async def send(message):
            messages.append(message)

        async def run():
            receive = await _single_body_receive(b"{}")
            await middleware(_scope("/mcp"), receive, send)

        asyncio.run(run())

        headers = dict(messages[0]["headers"])
        self.assertIn(b'scope="prompts:write"', headers[b"www-authenticate"])

    def test_rejects_oversized_content_length_before_calling_inner_app(self):
        inner_called = False

        async def inner(scope, receive, send):
            nonlocal inner_called
            inner_called = True

        middleware = McpRequestProtectionMiddleware(inner)
        messages = []

        async def send(message):
            messages.append(message)

        async def run():
            receive = await _single_body_receive(b"")
            await middleware(
                _scope("/register", headers=[(b"content-length", b"65537")]),
                receive,
                send,
            )

        with patch("services.mcp_request_protection.run_blocking", return_value=(True, 0, 0)):
            asyncio.run(run())

        self.assertFalse(inner_called)
        self.assertEqual(messages[0]["status"], 413)

    def test_rate_limited_authorize_request_returns_retry_after(self):
        async def inner(scope, receive, send):
            self.fail("Inner app must not receive a rate-limited request")

        middleware = McpRequestProtectionMiddleware(inner)
        messages = []

        async def send(message):
            messages.append(message)

        async def run():
            receive = await _single_body_receive(b"")
            await middleware(_scope("/authorize", method="GET"), receive, send)

        with patch("services.mcp_request_protection.run_blocking", return_value=(False, 0, 42)):
            asyncio.run(run())

        self.assertEqual(messages[0]["status"], 429)
        self.assertIn((b"retry-after", b"42"), messages[0]["headers"])

    def test_limited_request_body_is_replayed_to_inner_app(self):
        received = []

        async def inner(scope, receive, send):
            received.append(await receive())
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = McpRequestProtectionMiddleware(inner)
        messages = []

        async def send(message):
            messages.append(message)

        async def run():
            receive = await _single_body_receive(b'{"redirect_uris":["https://client.example/callback"]}')
            await middleware(_scope("/register"), receive, send)

        with patch("services.mcp_request_protection.run_blocking", return_value=(True, 0, 0)):
            asyncio.run(run())

        self.assertEqual(messages[0]["status"], 200)
        self.assertEqual(received[0]["body"], b'{"redirect_uris":["https://client.example/callback"]}')
