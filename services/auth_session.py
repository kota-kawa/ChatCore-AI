from __future__ import annotations

from fastapi import Request

from services.account_sessions import park_current_session
from services.csrf import CSRF_SESSION_KEY
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
    session = request.session
    current_user_id = session.get("user_id")
    signed_in_as_another_user = isinstance(current_user_id, int) and current_user_id != int(user_id)
    # 別アカウントでログイン中なら、そのセッションを破棄せず待機に回して後から切り替えられるようにする。
    # それ以外はセッション固定化攻撃（Session Fixation）を防ぐために旧IDを破棄する。どちらでも新しいIDが発行される。
    # When another account is signed in, park its session instead of discarding it so the user can
    # switch back. Otherwise discard the old ID to prevent session fixation. A fresh ID is issued either way.
    if signed_in_as_another_user and park_current_session(request):
        # 新しいアカウントのセッションは空から作る。管理者フラグなど、元のアカウントの
        # セッションに載っていた値を引き継がせない。CSRF トークンだけは、このページが
        # 取得済みの値で次のリクエストを送るので残す。
        # Start the new account's session from scratch so nothing the other account's session
        # held (the admin flag, for example) carries over. Only the CSRF token stays, because
        # this page sends its next request with the token it already fetched.
        csrf_token = session.get(CSRF_SESSION_KEY)
        session.clear()
        if csrf_token is not None:
            session[CSRF_SESSION_KEY] = csrf_token
    else:
        rotate_session_identifier(request)
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
