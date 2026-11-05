"""外部 HTTP 呼び出し（Web 検索・メール送信など）が共有する requests.Session と薄いラッパーを提供する。

Provides the shared requests.Session and thin wrappers used by outbound HTTP calls such as web search and email sending.
"""

from __future__ import annotations

import threading
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from services.env_settings import env_int

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


# コネクションプールの大きさを環境変数 HTTP_POOL_MAXSIZE（既定 32）で決める。接続先ホスト数の上限と同時接続数の上限を同じ値に揃える。
# Size the connection pool from HTTP_POOL_MAXSIZE (default 32), using one value for both the host-pool count and the per-host cap.
def _build_adapter() -> HTTPAdapter:
    pool_maxsize = env_int("HTTP_POOL_MAXSIZE", 32)
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
