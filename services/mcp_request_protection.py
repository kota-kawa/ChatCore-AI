"""認証前の MCP OAuth 入口（登録・認可など）に対する濫用対策。IP ごとのレート制限と、リクエスト本文サイズの上限を課す。

Abuse protections for unauthenticated MCP OAuth entry points: per-IP rate limits and a request body size cap.
"""

from __future__ import annotations

from fastapi import Request
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from services.async_utils import run_blocking
from services.auth_limits import consume_rate_limit, get_request_client_ip
from services.mcp_config import (
    get_mcp_authorize_rate_limit_per_10_minutes,
    get_mcp_dcr_rate_limit_per_hour,
    get_mcp_machine_max_body_bytes,
)

# 本文サイズ上限をかけるパス。
# Paths subject to the body size cap.
MCP_BODY_LIMIT_PATHS = frozenset({"/mcp", "/register", "/token", "/revoke"})
# レート制限をかけるパスごとの (キー接頭辞, 上限を返す関数, 窓の秒数)。上限は環境変数で変えられるよう呼び出し時に取得する。
# Per rate-limited path: (key prefix, getter for the limit, window in seconds); the limit is read at call time so env changes apply.
MCP_RATE_LIMITS = {
    "/register": ("mcp_dcr:ip", get_mcp_dcr_rate_limit_per_hour, 60 * 60),
    "/authorize": (
        "mcp_authorize:ip",
        get_mcp_authorize_rate_limit_per_10_minutes,
        10 * 60,
    ),
}


# 固定の JSON 本文で応答を返す（429/413 などのエラー用）。
# Send a response with a fixed JSON body (used for errors such as 429 and 413).
async def _send_json(send: Send, status: int, payload: bytes, headers: list[tuple[bytes, bytes]]) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), *headers],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class McpRequestProtectionMiddleware:
    """公開 OAuth 入口にレート制限をかけ、MCP リクエスト本文のサイズを制限する。

    Rate-limit public OAuth entry points and cap MCP request bodies.
    """

    def __init__(self, app: ASGIApp, *, required_scope: str | None = None) -> None:
        self.app = app
        self.required_scope = required_scope

    def __getattr__(self, name: str):
        # 包んでいるアプリの属性を委譲する（mcp_server.get_mcp_lifespan_context が `app.router` を参照するため）。
        # Delegate unknown attributes to the wrapped app (mcp_server.get_mcp_lifespan_context reads `app.router`).
        return getattr(self.app, name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if not await self._allow_request(scope, path, send):
            return

        # /mcp の認証失敗(401/403)には、必要な scope を WWW-Authenticate へ補う。
        # For /mcp authentication failures (401/403), add the required scope to WWW-Authenticate.
        response_send = self._scope_aware_send(send) if path == "/mcp" else send

        if path not in MCP_BODY_LIMIT_PATHS or scope.get("method", "GET").upper() in {"GET", "HEAD"}:
            await self.app(scope, receive, response_send)
            return

        # 本文付きのリクエストは、Content-Length で先に弾き、無ければ読みながらサイズを数えて上限を守る。
        # For requests with a body, reject early by Content-Length, otherwise count while reading to enforce the cap.
        max_bytes = get_mcp_machine_max_body_bytes()
        content_length = Headers(scope=scope).get("content-length")
        if content_length and self._content_length_exceeds_limit(content_length, max_bytes):
            await self._body_too_large(send)
            return

        body = await self._read_limited_body(receive, max_bytes)
        if body is None:
            await self._body_too_large(send)
            return

        # 本文はすでに読み切ったので、内側のアプリには読み込んだ本文を1回だけ再生して渡す。
        # The body is already consumed, so replay it once to the inner app.
        sent = False

        async def replay_receive() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, response_send)

    def _scope_aware_send(self, send: Send) -> Send:
        """MCP の認証チャレンジに RFC 6750 の scope 案内を足す。

    Add RFC 6750 scope guidance to MCP authentication challenges.
    """
        required_scope = self.required_scope
        if not required_scope:
            return send

        async def send_with_scope(message: Message) -> None:
            if message["type"] == "http.response.start" and message.get("status") in {401, 403}:
                headers = list(message.get("headers", []))
                updated_headers: list[tuple[bytes, bytes]] = []
                for name, value in headers:
                    if name.lower() == b"www-authenticate" and b"scope=" not in value.lower():
                        value += f', scope="{required_scope}"'.encode("ascii")
                    updated_headers.append((name, value))
                message = {**message, "headers": updated_headers}
            await send(message)

        return send_with_scope

    async def _allow_request(self, scope: Scope, path: str, send: Send) -> bool:
        # レート制限の対象パスでなければ許可し、対象なら IP ごとに消費して、超過時は 429 を返して False を返す。
        # Allow paths without a rate limit; otherwise consume per client IP and, when exceeded, send 429 and return False.
        rate_limit = MCP_RATE_LIMITS.get(path)
        if rate_limit is None:
            return True
        key_prefix, get_limit, window_seconds = rate_limit
        request = Request(scope)
        allowed, _, retry_after = await run_blocking(
            consume_rate_limit,
            key_prefix,
            get_request_client_ip(request),
            limit=get_limit(),
            window_seconds=window_seconds,
        )
        if allowed:
            return True
        await _send_json(
            send,
            429,
            b'{"error":"rate_limited","error_description":"Too many MCP OAuth requests."}',
            [(b"retry-after", str(retry_after).encode("ascii"))],
        )
        return False

    @staticmethod
    def _content_length_exceeds_limit(content_length: str, max_bytes: int) -> bool:
        # 数値でない Content-Length は超過とみなさず、後段の読み込み時のサイズ確認に任せる。
        # A non-numeric Content-Length is not treated as exceeding; the size check while reading still applies.
        try:
            return int(content_length) > max_bytes
        except (TypeError, ValueError):
            return False

    @staticmethod
    async def _read_limited_body(receive: Receive, max_bytes: int) -> bytes | None:
        # 上限を超えたら None。接続が切れたら空のバイト列を返す。
        # Return None once the cap is exceeded, and empty bytes if the client disconnects.
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return b""
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > max_bytes:
                return None
            chunks.append(chunk)
            if not message.get("more_body", False):
                return b"".join(chunks)

    @staticmethod
    async def _body_too_large(send: Send) -> None:
        await _send_json(
            send,
            413,
            b'{"error":"request_too_large","error_description":"MCP request body is too large."}',
            [],
        )
