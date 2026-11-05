"""Google OAuth ログインの途中状態（state・PKCE の code_verifier・戻り先）を Redis に短時間だけ保存し、コールバック時に一度だけ取り出す。

Keeps the in-flight state of a Google OAuth login (state, PKCE code_verifier, redirect target) in Redis for a short time
and hands it out exactly once at callback time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from services.cache import get_redis_client, mark_redis_unavailable

GOOGLE_OAUTH_TRANSACTION_TTL_SECONDS = 600
GOOGLE_OAUTH_TRANSACTION_KEY_PREFIX = "google_oauth_transaction:"
GOOGLE_OAUTH_TRANSACTION_COOKIE_NAME = "google_oauth_transaction"


@dataclass(frozen=True)
class GoogleOAuthTransaction:
    """短時間だけ有効なGoogle OAuth認証トランザクション。

    A short-lived Google OAuth authentication transaction.
    """

    state: str
    code_verifier: str
    redirect_uri: str
    next_path: str | None


def _transaction_key(state: str) -> str:
    return f"{GOOGLE_OAUTH_TRANSACTION_KEY_PREFIX}{state}"


def _valid_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def store_google_oauth_transaction(
    *,
    state: str,
    code_verifier: str,
    redirect_uri: str,
    next_path: str | None,
) -> bool:
    """OAuth callbackに必要な状態をRedisへ短時間だけ保存する。
    入力が不正、Redis が使えない、または同じ state が既にある場合は False を返す。

    Store the state needed by the OAuth callback in Redis for a short time.
    Returns False for invalid input, an unavailable Redis, or a state that already exists.
    """
    if not all(
        _valid_text(value)
        for value in (state, code_verifier, redirect_uri)
    ):
        return False
    if next_path is not None and not _valid_text(next_path):
        return False

    redis_client = get_redis_client()
    if redis_client is None:
        return False

    payload = json.dumps(
        {
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "next_path": next_path,
        },
        ensure_ascii=False,
    )
    try:
        # 同じstateの再利用を受け付けず、認証開始を一意に保つ。
        # NX prevents a state value from being overwritten by another flow.
        stored = redis_client.set(
            _transaction_key(state),
            payload,
            ex=GOOGLE_OAUTH_TRANSACTION_TTL_SECONDS,
            nx=True,
        )
    except Exception as exc:
        mark_redis_unavailable(exc)
        return False
    return bool(stored)


def _consume_raw(redis_client: Any, key: str) -> Any:
    """Redis 6.2以降のGETDELで一度だけ値を取り出す。

    Fetch a value exactly once with GETDEL (Redis 6.2 or later).
    """
    getdel = getattr(redis_client, "getdel", None)
    if callable(getdel):
        return getdel(key)
    # redis-pyの実装差分がある場合も、GETDELコマンド自体は原子的に実行する。
    # Even when redis-py lacks a getdel method, the GETDEL command itself still runs atomically.
    return redis_client.execute_command("GETDEL", key)


def consume_google_oauth_transaction(state: str) -> GoogleOAuthTransaction | None:
    """stateに紐づくOAuth状態を原子的に読み取り、直ちに削除する。
    見つからない・壊れている場合は None を返す。使い捨てなので、コールバックの再送では再利用できない。

    Atomically read the OAuth state tied to ``state`` and delete it immediately.
    Returns None when missing or malformed. It is single-use, so a replayed callback cannot reuse it.
    """
    if not _valid_text(state):
        return None

    redis_client = get_redis_client()
    if redis_client is None:
        return None

    try:
        raw_payload = _consume_raw(redis_client, _transaction_key(state))
    except Exception as exc:
        mark_redis_unavailable(exc)
        return None
    if raw_payload is None:
        return None

    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    code_verifier = payload.get("code_verifier")
    redirect_uri = payload.get("redirect_uri")
    next_path = payload.get("next_path")
    if not _valid_text(code_verifier) or not _valid_text(redirect_uri):
        return None
    if next_path is not None and not _valid_text(next_path):
        next_path = None

    return GoogleOAuthTransaction(
        state=state,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        next_path=next_path,
    )
