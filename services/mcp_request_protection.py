"""Abuse protections for unauthenticated MCP OAuth entry points."""

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

MCP_BODY_LIMIT_PATHS = frozenset({"/mcp", "/register", "/token", "/revoke"})
MCP_RATE_LIMITS = {
    "/register": ("mcp_dcr:ip", get_mcp_dcr_rate_limit_per_hour, 60 * 60),
    "/authorize": (
        "mcp_authorize:ip",
        get_mcp_authorize_rate_limit_per_10_minutes,
        10 * 60,
    ),
}


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
    """Rate-limit public OAuth entry points and cap MCP request bodies."""

    def __init__(self, app: ASGIApp, *, required_scope: str | None = None) -> None:
        self.app = app
        self.required_scope = required_scope

    def __getattr__(self, name: str):
        return getattr(self.app, name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if not await self._allow_request(scope, path, send):
            return

        response_send = self._scope_aware_send(send) if path == "/mcp" else send

        if path not in MCP_BODY_LIMIT_PATHS or scope.get("method", "GET").upper() in {"GET", "HEAD"}:
            await self.app(scope, receive, response_send)
            return

        max_bytes = get_mcp_machine_max_body_bytes()
        content_length = Headers(scope=scope).get("content-length")
        if content_length and self._content_length_exceeds_limit(content_length, max_bytes):
            await self._body_too_large(send)
            return

        body = await self._read_limited_body(receive, max_bytes)
        if body is None:
            await self._body_too_large(send)
            return

        sent = False

        async def replay_receive() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, response_send)

    def _scope_aware_send(self, send: Send) -> Send:
        """Add RFC 6750 scope guidance to MCP authentication challenges."""
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
        try:
            return int(content_length) > max_bytes
        except (TypeError, ValueError):
            return False

    @staticmethod
    async def _read_limited_body(receive: Receive, max_bytes: int) -> bytes | None:
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
