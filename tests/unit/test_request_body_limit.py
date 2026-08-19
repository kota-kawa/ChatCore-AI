from __future__ import annotations

import asyncio
import unittest

from fastapi import FastAPI, Request

from services.request_body_limit import RequestBodySizeLimitMiddleware


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


if __name__ == "__main__":
    unittest.main()
