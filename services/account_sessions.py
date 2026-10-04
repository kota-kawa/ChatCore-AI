"""同じブラウザで複数アカウントのログイン状態を保持する（待機セッション）。

表示中のアカウントは従来どおり `session` Cookie が指す 1 件で、ほかのログイン中アカウントの
セッション ID を「待機」として別の HttpOnly Cookie に並べる。切り替えは表示中と待機の入れ替えで、
セッション本体はどちらも Redis にあり、Cookie には参照 ID しか置かない。

Keep several accounts signed in on one browser ("parked" sessions). The active account is
still the single session the `session` cookie points at; the other signed-in accounts'
session IDs sit in a separate HttpOnly cookie. Switching swaps the active session with a
parked one. Session bodies stay in Redis either way; cookies only carry reference IDs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from starlette.types import Scope

from services.cache import get_redis_client, mark_redis_unavailable
from services.session_scope import (
    MAX_PARKED_SESSIONS,
    PARKED_SESSION_FLAG,
    PARKED_SESSION_IDS_ORIGINAL_SCOPE_KEY,
    PARKED_SESSION_IDS_SCOPE_KEY,
    SESSION_IDS_TO_DELETE_SCOPE_KEY,
    SESSION_RESTORE_RESTORED,
    SESSION_RESTORE_STATUS_SCOPE_KEY,
    session_redis_key,
)


@dataclass(frozen=True)
class ParkedSession:
    session_id: str
    user_id: int
    data: dict[str, Any]


def _parked_session_ids(scope: Scope) -> list[str]:
    session_ids = scope.get(PARKED_SESSION_IDS_SCOPE_KEY)
    return list(session_ids) if isinstance(session_ids, list) else []


def _restorable_current_session_id(request: Request) -> str | None:
    # Redis から復元できたセッションだけが待機に回せる。復元できていない ID を並べても切り替え先にならない。
    # Only a session that was restored from Redis can be parked; any other ID would never resolve.
    session_id = request.scope.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    if request.scope.get(SESSION_RESTORE_STATUS_SCOPE_KEY) != SESSION_RESTORE_RESTORED:
        return None
    return session_id


def park_current_session(request: Request) -> bool:
    """表示中のセッションを待機に回し、このリクエストのセッションへ新しい ID を割り当てさせる。

    Redis 上のレコードの更新（待機の目印、重複と上限の整理）は、応答を返す直前に
    `settle_parked_sessions` が行う。
    Park the active session and let this request's session be saved under a fresh ID. The Redis
    side (parked marker, duplicates, the limit) is settled by `settle_parked_sessions` right
    before the response is sent.
    """
    session_id = _restorable_current_session_id(request)
    if session_id is None:
        return False
    request.scope[PARKED_SESSION_IDS_SCOPE_KEY] = [
        session_id,
        *(item for item in _parked_session_ids(request.scope) if item != session_id),
    ]
    request.scope["session_id"] = None
    return True


def _decode_session(payload: Any) -> dict[str, Any] | None:
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_parked_sessions(redis_client: Any, scope: Scope) -> list[ParkedSession]:
    """待機セッションを Redis から読み、切り替え先にならないものを除く。

    期限切れ・ログイン状態を持たないものは除き、表示中のアカウントや先に並ぶ待機と同じ
    アカウントのもの（入り直した後に残った古いセッション）は Redis からも削除する。
    Read the parked sessions, leaving out the ones that cannot be switched to. Expired sessions and
    sessions without a login are skipped; sessions of the active account or of an account already
    listed (left behind after signing in again) are deleted from Redis as well.
    """
    current_user_id = scope["session"].get("user_id")
    current_session_id = scope.get("session_id")
    seen_user_ids = {current_user_id} if isinstance(current_user_id, int) else set()
    parked: list[ParkedSession] = []
    for session_id in _parked_session_ids(scope):
        if session_id == current_session_id:
            continue
        data = _decode_session(redis_client.get(session_redis_key(session_id)))
        user_id = data.get("user_id") if data else None
        if data is None or not isinstance(user_id, int):
            continue
        if user_id in seen_user_ids:
            redis_client.delete(session_redis_key(session_id))
            continue
        seen_user_ids.add(user_id)
        parked.append(ParkedSession(session_id=session_id, user_id=user_id, data=data))
    return parked


def load_parked_sessions(request: Request) -> list[ParkedSession] | None:
    """切り替え先にできる待機セッションを返し、できないものを一覧から外す。

    Redis を読めないときは一覧を変えずに None を返す（障害で待機アカウントを失わせない）。
    ブロッキング I/O なので `run_blocking` 経由で呼ぶ。
    Return the parked sessions that can be switched to and drop the rest from the list.
    Returns None and leaves the list alone when Redis is unreachable, so an outage never
    discards parked accounts. Blocking I/O: call it through `run_blocking`.
    """
    if not _parked_session_ids(request.scope):
        return []
    redis_client = get_redis_client()
    if redis_client is None:
        return None
    try:
        parked = _read_parked_sessions(redis_client, request.scope)
    except Exception as exc:
        mark_redis_unavailable(exc)
        return None
    request.scope[PARKED_SESSION_IDS_SCOPE_KEY] = [item.session_id for item in parked]
    return parked


def activate_parked_session(request: Request, target: ParkedSession, *, keep_current: bool) -> None:
    """待機セッションを表示中にする。

    keep_current が真なら今のセッションを待機へ回し（切り替え）、偽なら破棄する（ログアウト）。
    Make a parked session the active one. With keep_current the outgoing session is parked
    (switch); without it the outgoing session is deleted (sign-out).
    """
    session_ids = [item for item in _parked_session_ids(request.scope) if item != target.session_id]
    current_session_id = request.scope.get("session_id")
    if keep_current and _restorable_current_session_id(request) is not None:
        session_ids = [current_session_id, *session_ids]
    elif isinstance(current_session_id, str) and current_session_id:
        request.scope.setdefault(SESSION_IDS_TO_DELETE_SCOPE_KEY, set()).add(current_session_id)
    request.scope[PARKED_SESSION_IDS_SCOPE_KEY] = session_ids
    request.scope["session"] = {key: value for key, value in target.data.items() if key != PARKED_SESSION_FLAG}
    request.scope["session_id"] = target.session_id


def settle_parked_sessions(scope: Scope, max_age: int | None) -> list[str]:
    """このリクエストが変えた待機一覧を Redis に反映し、Cookie に書く一覧を返す。

    セッションミドルウェアが、表示中のセッションを保存した後に呼ぶ。新しく待機に回った
    セッションへ目印を付け、重複と上限超過を削除する。Redis を読めないときは一覧をそのまま返す。
    Apply this request's changes to the parked list in Redis and return the list for the cookie.
    Called by the session middleware after it saved the active session. Newly parked sessions get
    the parked marker; duplicates and sessions beyond the limit are deleted. When Redis is
    unreachable the list is returned unchanged.
    """
    session_ids = _parked_session_ids(scope)
    newly_parked = set(session_ids) - set(scope.get(PARKED_SESSION_IDS_ORIGINAL_SCOPE_KEY) or ())
    redis_client = get_redis_client() if newly_parked else None
    if redis_client is None:
        return session_ids
    try:
        parked = _read_parked_sessions(redis_client, scope)
        for overflow in parked[MAX_PARKED_SESSIONS:]:
            redis_client.delete(session_redis_key(overflow.session_id))
        parked = parked[:MAX_PARKED_SESSIONS]
        for item in parked:
            if item.session_id in newly_parked:
                payload = json.dumps({**item.data, PARKED_SESSION_FLAG: True}, ensure_ascii=False)
                redis_client.set(session_redis_key(item.session_id), payload, ex=max_age)
    except Exception as exc:
        mark_redis_unavailable(exc)
        return session_ids
    return [item.session_id for item in parked]
