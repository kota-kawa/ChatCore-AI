import asyncio
import unittest
from unittest.mock import patch

from services.session_middleware import HybridSessionMiddleware


class McpSessionBypassTestCase(unittest.TestCase):
    def test_mcp_path_does_not_restore_or_commit_a_web_session(self):
        async def downstream(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        middleware = HybridSessionMiddleware(
            downstream,
            secret_key="test-secret",
            bypass_paths=("/mcp",),
        )
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": []}
        with patch.object(middleware, "_restore_session") as restore_session, patch.object(
            middleware, "_commit_session"
        ) as commit_session:
            asyncio.run(middleware(scope, receive, send))

        restore_session.assert_not_called()
        commit_session.assert_not_called()
        self.assertEqual(messages[0]["status"], 200)
