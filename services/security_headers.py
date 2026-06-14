from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 日本語: アプリの基本セキュリティを高めるためのContent-Security-Policy (CSP) の設定値。
# English: Configuration value of Content-Security-Policy (CSP) to enhance basic application security.
CONTENT_SECURITY_POLICY = (
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)

# 日本語: レスポンスに適用される標準的なセキュリティヘッダーのマッピング。
# English: Mapping of standard security headers applied to HTTP responses.
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


# 日本語: すべてのHTTPレスポンスに定義されたセキュリティヘッダーを挿入するASGIミドルウェア。
# English: ASGI middleware that injects defined security headers into all HTTP responses.
class SecurityHeadersMiddleware:
    # 日本語: ミドルウェアインスタンスを初期化します。
    # English: Initialize the middleware instance.
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    # 日本語: リクエストを処理し、レスポンス開始時にセキュリティヘッダーを追加します。
    # English: Process the request and append security headers at the start of the response.
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # 日本語: HTTPリクエスト以外のスコープ（WebSocketやLifespanなど）は処理せずに次のアプリへ委譲します。
        # English: Pass through non-HTTP scopes (such as WebSocket or Lifespan) directly.
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # 日本語: レスポンス開始メッセージの場合に、定義された各セキュリティヘッダーを挿入するラッパー関数。
        # English: A wrapper function that inserts the defined security headers when the response starts.
        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        return await self.app(scope, receive, send_wrapper)
