"""Streaming request-body limits for narrow, high-risk upload endpoints."""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodySizeLimitMiddleware:
    """Reject oversize request streams before multipart parsing writes temp files."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        path: str,
        max_bytes: int,
    ) -> None:
        self.app = app
        self.path = path
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("path") != self.path
            or scope.get("method") != "POST"
        ):
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                await JSONResponse(
                    {"error": "Content-Lengthが不正です。"}, status_code=400
                )(scope, receive, send)
                return
            if declared_size > self.max_bytes:
                await JSONResponse(
                    {"error": "アップロードリクエストのサイズが上限を超えています。"},
                    status_code=413,
                )(scope, receive, send)
                return

        received_bytes = 0

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="アップロードリクエストのサイズが上限を超えています。",
                    )
            return message

        await self.app(scope, limited_receive, send)
