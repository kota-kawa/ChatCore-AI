from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

from services.security import constant_time_compare

CSRF_SESSION_KEY = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_or_create_csrf_token(request: Request) -> str:
    session = request.session
    # 既存トークンがあれば再利用し、無ければ新規発行して保存する
    # Reuse existing token; otherwise issue and persist a new one.
    token = session.get(CSRF_SESSION_KEY)
    if isinstance(token, str) and token:
        return token

    token = secrets.token_urlsafe(32)
    session[CSRF_SESSION_KEY] = token
    return token


async def require_csrf(request: Request) -> None:
    # 安全なメソッドでは検証不要として早期リターンする
    # Skip CSRF checks for safe HTTP methods.
    if request.method.upper() not in UNSAFE_METHODS:
        return

    expected_token = request.session.get(CSRF_SESSION_KEY)
    provided_token = request.headers.get(CSRF_HEADER_NAME)

    if not isinstance(expected_token, str) or not expected_token:
        raise HTTPException(status_code=403, detail="CSRF token is missing in session")

    if not isinstance(provided_token, str) or not provided_token:
        raise HTTPException(status_code=403, detail="CSRF token is missing")

    if not constant_time_compare(provided_token, expected_token):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")
