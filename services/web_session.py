from __future__ import annotations

from typing import List, Tuple

from fastapi import Request


# 日本語: set session permanent の設定処理を担当します。
# English: Handle setting for set session permanent.
def set_session_permanent(session: dict, value: bool) -> None:
    # セッション永続化フラグを明示的に付与/削除する
    # Explicitly set or clear the session permanence flag.
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if value:
        session["_permanent"] = True
    else:
        session.pop("_permanent", None)


# 日本語: flash に関する処理の入口です。
# English: Entry point for logic related to flash.
def flash(request: Request, message: str, category: str = "message") -> None:
    # セッションに一時メッセージを積む
    # Push a flash message into session storage.
    flashes: List[Tuple[str, str]] = request.session.setdefault("_flashes", [])
    flashes.append((category, message))


# 日本語: get flashed messages の取得処理を担当します。
# English: Handle fetching for get flashed messages.
def get_flashed_messages(
    request: Request, *, with_categories: bool = False
) -> List[str] | List[Tuple[str, str]]:
    # 1回読み取りで消費されるフラッシュメッセージを取得する
    # Pop one-time flash messages from session.
    flashes = request.session.pop("_flashes", [])
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if with_categories:
        return flashes
    return [message for _, message in flashes]
