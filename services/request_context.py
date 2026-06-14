from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

# 日本語: リクエストコンテキスト情報を保持するコンテキスト変数
# English: Context variables for storing request context information.
_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_request_method_var: ContextVar[str | None] = ContextVar("request_method", default=None)
_request_path_var: ContextVar[str | None] = ContextVar("request_path", default=None)

logger = logging.getLogger("chatcore.request")


# 日本語: 現在のスレッド/コンテキストに紐付けられたリクエストメタデータ（ID、メソッド、パス）を取得します。
# English: Retrieve the request metadata (ID, method, path) bound to the current context.
def get_request_context() -> dict[str, str | None]:
    # 日本語: ContextVar から現在リクエスト情報を取り出します。
    # English: Read current request metadata from ContextVars.
    return {
        "request_id": _request_id_var.get(),
        "request_method": _request_method_var.get(),
        "request_path": _request_path_var.get(),
    }


# 日本語: ログレコードにリクエストコンテキスト情報（Request ID等）を付与するためのログフィルター
# English: A logging filter that attaches request context information (such as Request ID) to log records.
class RequestContextFilter(logging.Filter):
    # 日本語: ログレコードをフィルタリングし、リクエストのメタデータを追加します。
    # English: Filter the log record and inject request metadata into it.
    def filter(self, record: logging.LogRecord) -> bool:
        context = get_request_context()
        # 日本語: ログ整形時に未設定項目は "-" を入れて欠損を明示します。
        # English: Fill missing fields with "-" to keep log output explicit and stable.
        record.request_id = context["request_id"] or "-"
        record.request_method = context["request_method"] or "-"
        record.request_path = context["request_path"] or "-"
        return True


# 日本語: リクエストIDやHTTPメソッド、パスを ContextVar に設定し、レスポンスヘッダーにRequest IDを付与するASGIミドルウェア
# English: ASGI middleware that stores request ID, HTTP method, and path in ContextVars, and adds the Request ID to response headers.
class RequestContextMiddleware:
    # 日本語: ミドルウェアインスタンスを初期化します。
    # English: Initialize the middleware instance.
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    # 日本語: リクエストを処理し、コンテキスト変数の設定とクリーンアップを行います。
    # English: Process the request, setting up and cleaning up context variables.
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # 日本語: HTTPリクエスト以外（WebSocket や Lifespan 等）の場合は処理をスキップして次のアプリに委譲します。
        # English: Skip processing and delegate to the next app for non-HTTP scopes (e.g. WebSocket or Lifespan).
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        # 日本語: 受信ヘッダーの Request ID を優先し、無ければサーバー側で新しいIDを生成します。
        # English: Prefer inbound request ID header and generate one when absent.
        request_id = _extract_request_id(scope) or str(uuid.uuid4())
        method = scope.get("method") or "-"
        path = scope.get("path") or "-"

        request_id_token = _request_id_var.set(request_id)
        method_token = _request_method_var.set(method)
        path_token = _request_path_var.set(path)

        status_code = 500

        # 日本語: レスポンス開始メッセージの場合、ステータスコードを取得してヘッダーにRequest-IDを追加するラッパー関数
        # English: A wrapper function to capture status code and append Request-ID to response headers.
        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        # 日本語: リクエスト処理を実行し、完了時に所要時間を計測・ログ出力してコンテキスト変数をリセットします。
        # English: Execute the request handler, log the response duration, and restore context variables upon completion.
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
            # 日本語: 応答後は ContextVar を必ず復元し、別リクエストへの値漏れを防ぎます。
            # English: Always reset ContextVars to avoid leaking data to other requests.
            _request_id_var.reset(request_id_token)
            _request_method_var.reset(method_token)
            _request_path_var.reset(path_token)


# 日本語: リクエストヘッダーから X-Request-ID ヘッダーの値を抽出します。
# English: Extract the value of the X-Request-ID header from the request headers.
def _extract_request_id(scope: Scope) -> str | None:
    headers = scope.get("headers") or []
    # 日本語: 各ヘッダー項目を走査して Request ID ヘッダーを検索します。
    # English: Iterate through all headers to find the Request ID header.
    for key, value in headers:
        if key.lower() == REQUEST_ID_HEADER.lower().encode("latin-1"):
            try:
                candidate = value.decode("latin-1").strip()
            except UnicodeDecodeError:
                return None
            if candidate:
                return candidate
    return None
