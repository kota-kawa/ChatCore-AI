from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_request_method_var: ContextVar[str | None] = ContextVar("request_method", default=None)
_request_path_var: ContextVar[str | None] = ContextVar("request_path", default=None)

logger = logging.getLogger("chatcore.request")


def get_request_context() -> dict[str, str | None]:
    # ContextVar から現在リクエスト情報を取り出す
    # Read current request metadata from ContextVars.
    return {
        "request_id": _request_id_var.get(),
        "request_method": _request_method_var.get(),
        "request_path": _request_path_var.get(),
    }


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = get_request_context()
        # ログ整形時に未設定項目は "-" を入れて欠損を明示する
        # Fill missing fields with "-" to keep log output explicit and stable.
        record.request_id = context["request_id"] or "-"
        record.request_method = context["request_method"] or "-"
        record.request_path = context["request_path"] or "-"
        return True


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # HTTP 以外 (websocket/lifespan など) はそのまま委譲する
            # Pass through non-HTTP scopes (websocket/lifespan, etc.).
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        # 受信ヘッダーの Request ID を優先し、無ければサーバー側で採番する
        # Prefer inbound request ID header and generate one when absent.
        request_id = _extract_request_id(scope) or str(uuid.uuid4())
        method = scope.get("method") or "-"
        path = scope.get("path") or "-"

        request_id_token = _request_id_var.set(request_id)
        method_token = _request_method_var.set(method)
        path_token = _request_path_var.set(path)

        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.info(
                "request completed",
                extra={
                    "event": "http_request",
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            # 応答後は ContextVar を必ず戻し、別リクエストへの値漏れを防ぐ
            # Always reset ContextVars to avoid leaking data to other requests.
            _request_id_var.reset(request_id_token)
            _request_method_var.reset(method_token)
            _request_path_var.reset(path_token)


def _extract_request_id(scope: Scope) -> str | None:
    headers = scope.get("headers") or []
    for key, value in headers:
        if key.lower() == REQUEST_ID_HEADER.lower().encode("latin-1"):
            try:
                candidate = value.decode("latin-1").strip()
            except UnicodeDecodeError:
                return None
            if candidate:
                return candidate
    return None
