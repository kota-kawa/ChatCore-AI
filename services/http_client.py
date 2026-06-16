from __future__ import annotations

import os
import threading
from typing import Any

import requests
from requests.adapters import HTTPAdapter

# 外部HTTP呼び出し（Web検索・メール送信など）で再利用する共有 requests.Session。
# TCP/TLS コネクションをプールして使い回すことで、リクエスト毎の接続確立コストと
# ソケット枯渇を避け、1ワーカーあたりの捌けるスループットを高める。
# Shared requests.Session reused across outbound HTTP calls (web search, email, ...).
# Pooling and reusing TCP/TLS connections avoids per-request handshake cost and socket
# exhaustion, increasing the throughput a single worker can sustain.
#
# 注意: 自動リトライは付けない。POST など非冪等なリクエストの二重送信を避けるため、
# リトライ要否は呼び出し側（アプリ層の既存リトライ）に委ねる。
# NOTE: no automatic retries are configured; whether to retry is left to callers so that
# non-idempotent requests (e.g. POST email sends) are never silently duplicated.

_session_lock = threading.Lock()
_session: requests.Session | None = None


# 環境変数から正の整数を取得する（不正値・非正値は既定値へフォールバック）
# Read a positive int env var, falling back to the default on invalid/non-positive input.
def _get_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


# コネクションプール付きの HTTPAdapter を構築する
# Build an HTTPAdapter backed by a connection pool.
def _build_adapter() -> HTTPAdapter:
    pool_maxsize = _get_positive_int_env("HTTP_POOL_MAXSIZE", 32)
    return HTTPAdapter(
        pool_connections=pool_maxsize,
        pool_maxsize=pool_maxsize,
        max_retries=0,
    )


# 共有 requests.Session を取得する（スレッドセーフな遅延初期化）
# Get the shared requests.Session (thread-safe lazy initialization).
def get_http_session() -> requests.Session:
    global _session
    with _session_lock:
        if _session is None:
            session = requests.Session()
            adapter = _build_adapter()
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            _session = session
        return _session


# 共有 Session 経由で HTTP リクエストを送信する薄いラッパー
# Thin wrapper that issues an HTTP request through the shared session.
def request(method: str, url: str, **kwargs: Any) -> requests.Response:
    return get_http_session().request(method, url, **kwargs)


# 共有 Session 経由の GET ショートカット
# GET shortcut over the shared session.
def get(url: str, **kwargs: Any) -> requests.Response:
    return get_http_session().get(url, **kwargs)


# 共有 Session 経由の POST ショートカット
# POST shortcut over the shared session.
def post(url: str, **kwargs: Any) -> requests.Response:
    return get_http_session().post(url, **kwargs)
