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


# 日本語: get request context の取得処理を担当します。
# English: Handle fetching for get request context.
def get_request_context() -> dict[str, str | None]:
    # ContextVar から現在リクエスト情報を取り出す
    # Read current request metadata from ContextVars.
    return {
        "request_id": _request_id_var.get(),
        "request_method": _request_method_var.get(),
        "request_path": _request_path_var.get(),
    }


# 日本語: RequestContextFilter に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to RequestContextFilter.
class RequestContextFilter(logging.Filter):
    # 日本語: filter に関する処理の入口です。
    # English: Entry point for logic related to filter.
    def filter(self, record: logging.LogRecord) -> bool:
        context = get_request_context()
        # ログ整形時に未設定項目は "-" を入れて欠損を明示する
        # Fill missing fields with "-" to keep log output explicit and stable.
        record.request_id = context["request_id"] or "-"
        record.request_method = context["request_method"] or "-"
        record.request_path = context["request_path"] or "-"
        return True


# 日本語: RequestContextMiddleware に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to RequestContextMiddleware.
class RequestContextMiddleware:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    # 日本語: call に関する処理の入口です。
    # English: Entry point for logic related to call.
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
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

        # 日本語: send wrapper の送信処理を非同期で担当します。
        # English: Handle sending for send wrapper asynchronously.
        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
            # English: Switch the flow according to the current condition.
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
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


# 日本語: extract request id に関する処理の入口です。
# English: Entry point for logic related to extract request id.
def _extract_request_id(scope: Scope) -> str | None:
    headers = scope.get("headers") or []
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for key, value in headers:
        if key.lower() == REQUEST_ID_HEADER.lower().encode("latin-1"):
            try:
                candidate = value.decode("latin-1").strip()
            except UnicodeDecodeError:
                return None
            if candidate:
                return candidate
    return None
