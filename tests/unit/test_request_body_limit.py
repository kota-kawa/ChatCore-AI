from __future__ import annotations

import ast
import asyncio
import unittest
from pathlib import Path

from fastapi import FastAPI, Request

from services.avatar_storage import AVATAR_MAX_BYTES, AVATAR_MAX_REQUEST_BYTES
from services.request_body_limit import RequestBodySizeLimitMiddleware

REPO_ROOT = Path(__file__).resolve().parents[2]


def _registered_body_size_limits() -> dict[str, str]:
    """Read app.py and map each guarded path to the max_bytes symbol it is registered with."""
    module = ast.parse((REPO_ROOT / "app.py").read_text(encoding="utf-8"))
    registrations: dict[str, str] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_middleware":
            continue
        if not node.args or not isinstance(node.args[0], ast.Name):
            continue
        if node.args[0].id != "RequestBodySizeLimitMiddleware":
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        path = keywords.get("path")
        max_bytes = keywords.get("max_bytes")
        if isinstance(path, ast.Constant) and isinstance(max_bytes, ast.Name):
            registrations[str(path.value)] = max_bytes.id
    return registrations


class RequestBodySizeLimitMiddlewareTestCase(unittest.TestCase):
    def test_rejects_declared_oversize_upload_before_calling_app(self):
        called = False
        sent = []

        async def app(_scope, _receive, _send):
            nonlocal called
            called = True

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        middleware = RequestBodySizeLimitMiddleware(
            app,
            path="/prompt_share/api/prompts",
            max_bytes=10,
        )
        asyncio.run(
            middleware(
                {
                    "type": "http",
                    "path": "/prompt_share/api/prompts",
                    "method": "POST",
                    "headers": [(b"content-length", b"11")],
                },
                receive,
                send,
            )
        )

        self.assertFalse(called)
        self.assertEqual(sent[0]["status"], 413)

    def test_passes_a_within_limit_stream_to_the_app(self):
        sent = []
        received = []
        messages = iter(
            (
                {"type": "http.request", "body": b"123", "more_body": True},
                {"type": "http.request", "body": b"45", "more_body": False},
            )
        )

        async def app(_scope, receive, send):
            received.append(await receive())
            received.append(await receive())
            await send({"type": "http.response.start", "status": 201, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        middleware = RequestBodySizeLimitMiddleware(
            app,
            path="/prompt_share/api/prompts",
            max_bytes=5,
        )
        asyncio.run(
            middleware(
                {
                    "type": "http",
                    "path": "/prompt_share/api/prompts",
                    "method": "POST",
                    "headers": [],
                },
                receive,
                send,
            )
        )

        self.assertEqual(b"".join(item["body"] for item in received), b"12345")
        self.assertEqual(sent[0]["status"], 201)

    def test_rejects_chunked_stream_that_exceeds_limit_during_parsing(self):
        app = FastAPI()
        app.add_middleware(
            RequestBodySizeLimitMiddleware,
            path="/prompt_share/api/prompts",
            max_bytes=5,
        )

        @app.post("/prompt_share/api/prompts")
        async def endpoint(request: Request):
            await request.body()
            return {"ok": True}

        messages = iter(
            (
                {"type": "http.request", "body": b"123", "more_body": True},
                {"type": "http.request", "body": b"456", "more_body": False},
            )
        )
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        asyncio.run(
            app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "POST",
                    "scheme": "http",
                    "path": "/prompt_share/api/prompts",
                    "raw_path": b"/prompt_share/api/prompts",
                    "query_string": b"",
                    "headers": [],
                    "client": ("127.0.0.1", 1234),
                    "server": ("testserver", 80),
                },
                receive,
                send,
            )
        )

        self.assertEqual(sent[0]["status"], 413)

    def test_rejects_oversize_profile_upload_before_the_form_is_parsed(self):
        app = FastAPI()
        app.add_middleware(
            RequestBodySizeLimitMiddleware,
            path="/api/user/profile",
            max_bytes=AVATAR_MAX_REQUEST_BYTES,
        )
        parsed = False

        @app.post("/api/user/profile")
        async def endpoint(request: Request):
            nonlocal parsed
            await request.form()
            parsed = True
            return {"ok": True}

        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        asyncio.run(
            app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "POST",
                    "scheme": "http",
                    "path": "/api/user/profile",
                    "raw_path": b"/api/user/profile",
                    "query_string": b"",
                    "headers": [
                        (b"content-type", b"multipart/form-data; boundary=x"),
                        (b"content-length", str(AVATAR_MAX_REQUEST_BYTES + 1).encode()),
                    ],
                    "client": ("127.0.0.1", 1234),
                    "server": ("testserver", 80),
                },
                receive,
                send,
            )
        )

        self.assertFalse(parsed)
        self.assertEqual(sent[0]["status"], 413)

    def test_profile_request_limit_leaves_room_for_a_max_size_avatar(self):
        self.assertGreater(AVATAR_MAX_REQUEST_BYTES, AVATAR_MAX_BYTES)


class RequestBodySizeLimitRegistrationTestCase(unittest.TestCase):
    def test_upload_endpoints_are_guarded_by_the_body_size_middleware(self):
        self.assertEqual(
            _registered_body_size_limits(),
            {
                "/prompt_share/api/prompts": "PROMPT_ATTACHMENT_MAX_REQUEST_BYTES",
                "/api/user/profile": "AVATAR_MAX_REQUEST_BYTES",
            },
        )


if __name__ == "__main__":
    unittest.main()
