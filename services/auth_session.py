from __future__ import annotations

from fastapi import Request

from services.session_middleware import rotate_session_identifier
from services.web import set_session_permanent


# 認証に成功したユーザーのセッションを確立（初期化・クッキー固定化対策）する
# Establish and initialize an authenticated session for a successfully verified user
def establish_authenticated_session(request: Request, user_id: int, email: str) -> None:
    # セッション固定化攻撃（Session Fixation）を防ぐためにセッションIDをローテーションする
    # Rotate the session identifier to prevent session fixation attacks
    rotate_session_identifier(request)
    session = request.session
    # セッション内にログインユーザーのIDとメールアドレスを書き込む
    # Write the logged-in user's ID and email into the session dict
    session["user_id"] = int(user_id)
    session["user_email"] = email
    # セッションの永続化フラグを有効化する
    # Enable the permanent session persistence flag
    set_session_permanent(session, True)
