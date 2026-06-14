from __future__ import annotations

from fastapi import Request

from services.session_middleware import rotate_session_identifier
from services.web import set_session_permanent


# 認証に成功したユーザーのセッションを確立（初期化・クッキー固定化対策）する
# Establish and initialize an authenticated session for a successfully verified user.
# 日本語: establish authenticated session に関する処理の入口です。
# English: Entry point for logic related to establish authenticated session.
def establish_authenticated_session(request: Request, user_id: int, email: str) -> None:
    # 認証成功時のセッション確立処理を1か所に集約する
    # Centralize post-auth session establishment in one helper.
    # Reissue the session identifier and persist the authenticated user context.
    rotate_session_identifier(request)
    session = request.session
    session["user_id"] = int(user_id)
    session["user_email"] = email
    set_session_permanent(session, True)
