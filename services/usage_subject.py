"""Attribute API usage to the user (or guest) whose request caused it.

LLM 呼び出しは生成ワーカーやバックグラウンドのスレッドで走り、呼び出し側は誰の
リクエストかを知りません。そこでリクエストの入口で計上先を ContextVar に載せ、
スレッドへ処理を渡す箇所でコンテキストごと複製して運びます。
LLM calls run on generation workers and background threads that do not know whose
request they serve. The entry point stores the billing subject in a ContextVar, and every
hand-off to a thread carries a copy of the context along with the work.
"""

from __future__ import annotations

import hashlib
from contextvars import ContextVar

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from services.auth_limits import get_request_client_ip

# セッションを持たないリクエスト（MCP の機械向けエンドポイントなど）や、
# リクエストの外で動く処理の使用量。個人の上限には数えず、全体の合計にだけ入る。
# Usage from requests without a session (such as MCP machine endpoints) or from work
# outside any request. It never counts toward a person's limits, only toward the total.
SYSTEM_USAGE_SUBJECT = "system"

_usage_subject_var: ContextVar[str] = ContextVar("usage_subject", default=SYSTEM_USAGE_SUBJECT)


def user_usage_subject(user_id: int | str) -> str:
    return f"user:{int(user_id)}"


def guest_usage_subject(client_ip: str) -> str:
    # 接続元IPをそのまま保存しないようハッシュにする。
    # Hash the client IP so the address itself is never stored.
    digest = hashlib.sha256(client_ip.encode("utf-8", errors="replace")).hexdigest()
    return f"guest:{digest[:32]}"


def current_usage_subject() -> str:
    return _usage_subject_var.get()


def resolve_usage_subject(scope: Scope) -> str:
    """Return the billing subject for one HTTP request scope."""

    session = scope.get("session")
    if not isinstance(session, dict):
        return SYSTEM_USAGE_SUBJECT
    user_id = session.get("user_id")
    if user_id:
        try:
            return user_usage_subject(user_id)
        except (TypeError, ValueError):
            return SYSTEM_USAGE_SUBJECT
    return guest_usage_subject(get_request_client_ip(Request(scope)))


class UsageSubjectMiddleware:
    """Bind the billing subject for the lifetime of each HTTP request.

    セッションを読むため、セッションミドルウェアより内側に置く必要があります。
    It reads the session, so it must sit inside the session middleware.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _usage_subject_var.set(resolve_usage_subject(scope))
        try:
            await self.app(scope, receive, send)
        finally:
            _usage_subject_var.reset(token)
