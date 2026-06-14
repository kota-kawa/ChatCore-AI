from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_SECURITY_POLICY = (
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


# 日本語: SecurityHeadersMiddleware に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to SecurityHeadersMiddleware.
class SecurityHeadersMiddleware:
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
            return await self.app(scope, receive, send)

        # 日本語: send wrapper の送信処理を非同期で担当します。
        # English: Handle sending for send wrapper asynchronously.
        async def send_wrapper(message: Message) -> None:
            # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
            # English: Switch the flow according to the current condition.
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        return await self.app(scope, receive, send_wrapper)
