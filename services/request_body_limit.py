"""アップロード系の限られたエンドポイント向けに、リクエストボディのサイズ上限を受信中に強制するミドルウェア。

app.py が /prompt_share/api/prompts(添付画像)と /api/user/profile(アバター)に登録する。

Streaming request-body limits for narrow, high-risk upload endpoints.
Registered by app.py for /prompt_share/api/prompts (attachments) and /api/user/profile (avatars).
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


# 日本語: 指定パスの POST だけを対象にする ASGI ミドルウェア。マルチパート解析が一時ファイルを書く前に、
# 宣言サイズ(Content-Length)と実受信量の両方で上限を超えた要求を打ち切る。
# English: ASGI middleware limited to POST on one path. It rejects oversize requests, by declared Content-Length
# and by bytes actually received, before multipart parsing writes temp files.
class RequestBodySizeLimitMiddleware:
    # multipart解析が一時ファイルを作る前に、巨大なリクエストストリームを拒否する。
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

        # 日本語: まず宣言サイズで早期に弾く(本文を読まずに済む)。
        # English: Reject early on the declared size so the body is never read.
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

        # 日本語: Content-Length を偽る/省略(chunked)する要求に備え、受信したバイト数を数えて超過時に 413 にする。
        # English: Content-Length can be omitted (chunked) or understated, so count received bytes and raise 413 on overflow.
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
