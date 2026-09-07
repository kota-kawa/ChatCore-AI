from __future__ import annotations

from fastapi import Request


def set_session_permanent(session: dict, value: bool) -> None:
    # セッション永続化フラグを明示的に付与/削除する
    # Explicitly set or clear the session permanence flag.
    if value:
        session["_permanent"] = True
    else:
        session.pop("_permanent", None)


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
