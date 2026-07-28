from __future__ import annotations

from fastapi import Request

from services.i18n import (
    PREFERRED_LOCALE_LOADED_SESSION_KEY,
    PREFERRED_LOCALE_SESSION_KEY,
    normalize_locale,
)
from services.session_middleware import rotate_session_identifier
from services.web import set_session_permanent


# 認証に成功したユーザーのセッションを確立（初期化・クッキー固定化対策）する
# Establish and initialize an authenticated session for a successfully verified user
def establish_authenticated_session(
    request: Request,
    user_id: int,
    email: str,
    preferred_locale: str | None = None,
) -> None:
    # セッション固定化攻撃（Session Fixation）を防ぐためにセッションIDをローテーションする
    # Rotate the session identifier to prevent session fixation attacks
    rotate_session_identifier(request)
    session = request.session
    # セッション内にログインユーザーのIDとメールアドレスを書き込む
    # Write the logged-in user's ID and email into the session dict
    session["user_id"] = int(user_id)
    session["user_email"] = email
    normalized_locale = normalize_locale(preferred_locale)
    session.pop(PREFERRED_LOCALE_SESSION_KEY, None)
    session.pop(PREFERRED_LOCALE_LOADED_SESSION_KEY, None)
    if normalized_locale is not None:
        session[PREFERRED_LOCALE_SESSION_KEY] = normalized_locale
        session[PREFERRED_LOCALE_LOADED_SESSION_KEY] = True
    # セッションの永続化フラグを有効化する
    # Enable the permanent session persistence flag
    set_session_permanent(session, True)
