from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

from services.security import constant_time_compare

CSRF_SESSION_KEY = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


# セッションからCSRFトークンを取得、または新規に作成してセッションに格納し、そのトークンを返す
# Get the CSRF token from the session, or create a new one, store it in the session, and return it.
# 日本語: get or create csrf token の取得処理を担当します。
# English: Handle fetching for get or create csrf token.
def get_or_create_csrf_token(request: Request) -> str:
    session = request.session
    # 既存トークンがあれば再利用し、無ければ新規発行して保存する
    # Reuse existing token; otherwise issue and persist a new one.
    token = session.get(CSRF_SESSION_KEY)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if isinstance(token, str) and token:
        return token

    token = secrets.token_urlsafe(32)
    session[CSRF_SESSION_KEY] = token
    return token


# リクエストが安全でないメソッド（POST等）の場合にCSRFトークンを検証する
# Validate the CSRF token if the request uses an unsafe method (e.g., POST).
# 日本語: require csrf に関する処理の入口です。
# English: Entry point for logic related to require csrf.
async def require_csrf(request: Request) -> None:
    # 安全なメソッドでは検証不要として早期リターンする
    # Skip CSRF checks for safe HTTP methods.
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if request.method.upper() not in UNSAFE_METHODS:
        return

    expected_token = request.session.get(CSRF_SESSION_KEY)
    provided_token = request.headers.get(CSRF_HEADER_NAME)

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not isinstance(expected_token, str) or not expected_token:
        raise HTTPException(status_code=403, detail="CSRF token is missing in session")

    if not isinstance(provided_token, str) or not provided_token:
        raise HTTPException(status_code=403, detail="CSRF token is missing")

    if not constant_time_compare(provided_token, expected_token):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")
