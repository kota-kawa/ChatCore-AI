"""セッション辞書の永続化フラグ・ログイン中のユーザー ID・一度読むと消えるフラッシュメッセージを扱う小さなヘルパー。

Small helpers for the session's permanence flag, the signed-in user id and one-time flash messages kept in the session.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request


def set_session_permanent(session: dict, value: bool) -> None:
    # セッション永続化フラグを明示的に付与/削除する
    # Explicitly set or clear the session permanence flag.
    if value:
        session["_permanent"] = True
    else:
        session.pop("_permanent", None)


# セッションの user_id が整数のときだけ返す。それ以外は未ログイン扱いの None。
# Return the session user_id only when it is an int; otherwise None, treated as not signed in.
def user_id_from_session(session: dict[str, Any]) -> int | None:
    user_id = session.get("user_id")
    if isinstance(user_id, int):
        return user_id
    return None


# セッションからログイン中のユーザー ID を整数で返す。未ログインや不正な値は None。
# `user_id_from_session` と違い、数値の文字列も整数へ変換して受け入れる。
# Return the signed-in user id from the session as an int; None when signed out or the value is invalid.
# Unlike `user_id_from_session`, a numeric string is accepted and converted to an int.
def authenticated_user_id(request: Request) -> int | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def flash(request: Request, message: str, category: str = "message") -> None:
    # セッションに一時メッセージ（フラッシュメッセージ）を積む
    # Push a temporary flash message into session storage.
    flashes: list[tuple[str, str]] = request.session.setdefault("_flashes", [])
    flashes.append((category, message))


def get_flashed_messages(
    request: Request, *, with_categories: bool = False
) -> list[str] | list[tuple[str, str]]:
    # 1回読み取りで消費されるフラッシュメッセージを取得してセッションから消去する
    # Pop one-time flash messages from session and clear them from storage.
    flashes = request.session.pop("_flashes", [])
    if with_categories:
        return flashes
    return [message for _, message in flashes]
