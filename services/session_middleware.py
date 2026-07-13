from __future__ import annotations

import json
import logging
import secrets
from http.cookies import SimpleCookie
from typing import Any

from fastapi import Request
from itsdangerous import BadSignature, URLSafeSerializer
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from services.async_utils import run_blocking
from services.cache import get_redis_client, mark_redis_unavailable
from services.csrf import CSRF_SESSION_KEY

# ロガーの設定
# Configure logger
logger = logging.getLogger(__name__)

# 定数の定義
# Define constants
REDIS_BACKEND = "redis"
SESSION_IDS_TO_DELETE_SCOPE_KEY = "_session_ids_to_delete"


def rotate_session_identifier(request: Request) -> None:
    # ログイン成功時はセッションIDを再発行して fixation を防ぐ
    # Rotate the session identifier after authentication to mitigate session fixation.
    scope = request.scope
    current_session_id = scope.get("session_id")
    if isinstance(current_session_id, str) and current_session_id:
        pending = scope.setdefault(SESSION_IDS_TO_DELETE_SCOPE_KEY, set())
        pending.add(current_session_id)
    scope["session_id"] = None


class PermanentSessionMiddleware:
    # セッションは Redis にのみ保存する。Redis に書けない場合はセッションを発行せず Cookie をクリアする
    # Sessions are stored only in Redis. If Redis is unavailable the cookie is cleared
    # rather than written with a signed-but-unencrypted payload that would leak
    # verification codes, admin flags, and OAuth state to anyone who reads the cookie.
    def __init__(
        self,
        app: ASGIApp,
        *,
        secret_key: str,
        session_cookie: str = "session",
        max_age: int | None = None,
        path: str = "/",
        same_site: str = "lax",
        https_only: bool = False,
        bypass_paths: tuple[str, ...] = (),
    ) -> None:
        # 内部でハイブリッドミドルウェアを初期化する
        # Initialize the HybridSessionMiddleware internally
        self.inner = HybridSessionMiddleware(
            app,
            secret_key=secret_key,
            session_cookie=session_cookie,
            max_age=max_age,
            path=path,
            same_site=same_site,
            https_only=https_only,
            bypass_paths=bypass_paths,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # ASGI呼び出しをラップして内部ミドルウェアに委譲する
        # Wrap the ASGI call and delegate to the inner middleware
        await self.inner(scope, receive, send)


class HybridSessionMiddleware:
    # Redisベースのセッション管理を行うハイブリッドミドルウェアクラス
    # Hybrid middleware class that performs Redis-based session management
    def __init__(
        self,
        app: ASGIApp,
        *,
        secret_key: str,
        session_cookie: str = "session",
        max_age: int | None = None,
        path: str = "/",
        same_site: str = "lax",
        https_only: bool = False,
        bypass_paths: tuple[str, ...] = (),
    ) -> None:
        # ミドルウェア設定の初期化
        # Initialize middleware configurations
        self.app = app
        self.session_cookie = session_cookie
        self.max_age = max_age
        self.path = path
        self.same_site = same_site
        self.https_only = https_only
        self.bypass_paths = tuple(bypass_paths)
        self.serializer = URLSafeSerializer(secret_key, salt="strike.session")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # HTTPリクエスト以外のタイプはスルーする
        # Skip non-HTTP request types
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = str(scope.get("path") or "")
        if path in self.bypass_paths:
            return await self.app(scope, receive, send)

        # Cookieからセッション状態をロードし、Redisからデータを復元する
        # Load session state from cookie and restore data from Redis
        cookie_state = self._load_cookie_state(scope)
        session_data, session_id = await run_blocking(self._restore_session, cookie_state)
        # CSRFトークンが存在しない場合は新規生成してセッションに格納する
        # Generate and store a CSRF token in the session if it doesn't exist
        if CSRF_SESSION_KEY not in session_data:
            session_data[CSRF_SESSION_KEY] = secrets.token_urlsafe(32)
        scope["session"] = session_data
        scope["session_id"] = session_id

        # レスポンス送信時にセッションコミット処理を挟むためのラッパー
        # Wrapper to intercept response start and commit the session
        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                # レスポンス開始直前に保存することで、endpoint/middleware が最後に変更した
                # request.session の内容を Cookie 発行と Redis保存へ反映する。
                # Save session right before starting response to reflect any changes
                # to request.session in cookies and Redis storage.
                headers = MutableHeaders(scope=message)
                await run_blocking(self._commit_session, scope, headers)
            await send(message)

        return await self.app(scope, receive, send_wrapper)

    def _load_cookie_state(self, scope: Scope) -> dict[str, Any] | None:
        # Cookieから署名された値を読み込んでデシリアライズする
        # Load signed value from Cookie and deserialize it
        headers = Headers(scope=scope)
        cookie_header = headers.get("cookie")
        if not cookie_header:
            return None

        cookies = SimpleCookie()
        cookies.load(cookie_header)
        if self.session_cookie not in cookies:
            return None

        signed_value = cookies[self.session_cookie].value
        try:
            payload = self.serializer.loads(signed_value)
        except BadSignature:
            return None

        if isinstance(payload, str):
            # 旧実装の Redis-backed cookie は session_id 文字列だけを署名していた。
            # dict 形式へ移行後も既存ログインを壊さないため、ここで読み替える。
            # The old implementation signed only the session_id string.
            # Handle this case to avoid breaking existing logins.
            return {"backend": REDIS_BACKEND, "id": payload}
        if isinstance(payload, dict):
            # Legacy cookie-backed payloads ({"backend": "cookie", "data": {...}})
            # are intentionally ignored here: they used to embed sensitive session
            # data directly in the cookie, so we treat any such cookie as expired
            # to force the user to re-authenticate against the Redis-backed flow.
            # レガシーなクッキー保存型のセッションデータは意図的に無視する。
            if payload.get("backend") == REDIS_BACKEND:
                return payload
            return None
        return None

    def _restore_session(
        self, cookie_state: dict[str, Any] | None
    ) -> tuple[dict[str, Any], str | None]:
        # Redisからセッションデータを取得してロードする
        # Fetch and load session data from Redis
        if not cookie_state:
            return {}, None

        if cookie_state.get("backend") != REDIS_BACKEND:
            return {}, None

        session_id = cookie_state.get("id")
        if not isinstance(session_id, str) or not session_id:
            return {}, None

        redis_client = get_redis_client()
        if redis_client is None:
            return {}, None

        try:
            payload = redis_client.get(self._redis_key(session_id))
        except Exception as exc:
            mark_redis_unavailable(exc)
            return {}, None

        if not payload:
            return {}, None

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return {}, None
        if isinstance(data, dict):
            return data, session_id
        return {}, None

    def _commit_session(self, scope: Scope, headers: MutableHeaders) -> None:
        # セッションの変更内容をコミットし、必要に応じてCookieやRedisを更新する
        # Commit session changes and update cookies or Redis as necessary
        session = scope.get("session") or {}
        session_id = scope.get("session_id")
        pending_delete_ids = scope.get(SESSION_IDS_TO_DELETE_SCOPE_KEY) or set()

        if not session:
            # 空セッションは「ログアウト/無効化済み」とみなし、現在IDと rotation 前IDの両方を消す。
            # 古い Redis レコードを残すと、盗まれた古い Cookie が有効なままになる。
            # Empty sessions are treated as logged-out. Remove both current and pre-rotation IDs
            # to prevent stolen old cookies from remaining valid.
            for stale_session_id in pending_delete_ids:
                self._delete_session(stale_session_id)
            if session_id:
                self._delete_session(session_id)
            self._set_cookie(headers, "", max_age=0)
            return

        is_permanent = session.get("_permanent") is True
        cookie_max_age = self.max_age if is_permanent else None

        if not session_id:
            session_id = secrets.token_urlsafe(32)
            scope["session_id"] = session_id

        for stale_session_id in pending_delete_ids:
            if stale_session_id != session_id:
                self._delete_session(stale_session_id)
        scope[SESSION_IDS_TO_DELETE_SCOPE_KEY] = set()

        if self._save_session(session_id, session):
            # Cookie には Redis の参照IDだけを入れる。セッション本体は Redis 側に置く。
            # Store only the Redis reference ID in the cookie. The session body is kept in Redis.
            self._set_cookie(
                headers,
                self.serializer.dumps({"backend": REDIS_BACKEND, "id": session_id}),
                cookie_max_age,
            )
            return

        # Redis is unavailable: refuse to persist the session. We previously
        # fell back to writing the entire session dict into the cookie via a
        # signed-but-unencrypted serializer, which leaked email verification
        # codes, the is_admin flag, OAuth state and passkey challenges to
        # anyone who could read the cookie. Clearing the cookie forces the
        # user to re-authenticate once Redis comes back, which is the safe
        # failure mode.
        # Redisが利用不可の場合は、セッション維持を拒否してCookieをクリアする。
        logger.warning(
            "Session not persisted because Redis is unavailable; clearing session cookie."
        )
        scope["session"] = {}
        scope["session_id"] = None
        self._set_cookie(headers, "", max_age=0)

    def _save_session(self, session_id: str, session: dict[str, Any]) -> bool:
        # セッションデータをRedisに保存する
        # Save session data to Redis
        redis_client = get_redis_client()
        if redis_client is None:
            return False

        payload = json.dumps(session, ensure_ascii=False)
        try:
            if self.max_age is not None:
                redis_client.set(self._redis_key(session_id), payload, ex=self.max_age)
            else:
                redis_client.set(self._redis_key(session_id), payload)
        except Exception as exc:
            mark_redis_unavailable(exc)
            return False
        return True

    def _delete_session(self, session_id: str) -> None:
        # 指定されたセッションIDのデータをRedisから削除する
        # Delete the data of the specified session ID from Redis
        redis_client = get_redis_client()
        if redis_client is None:
            return
        try:
            redis_client.delete(self._redis_key(session_id))
        except Exception as exc:
            mark_redis_unavailable(exc)

    def _redis_key(self, session_id: str) -> str:
        # Redisのセッションキーを作成する
        # Create a Redis session key
        return f"session:{session_id}"

    def _set_cookie(
        self, headers: MutableHeaders, value: str, max_age: int | None = None
    ) -> None:
        # レスポンスヘッダーにセッションCookieを設定する
        # Set the session cookie in response headers
        cookie = SimpleCookie()
        cookie[self.session_cookie] = value
        cookie[self.session_cookie]["path"] = self.path
        cookie[self.session_cookie]["httponly"] = True
        if self.same_site:
            cookie[self.session_cookie]["samesite"] = self.same_site
        if self.https_only:
            cookie[self.session_cookie]["secure"] = True
        if max_age is not None:
            cookie[self.session_cookie]["max-age"] = str(max_age)
        if max_age == 0:
            cookie[self.session_cookie]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
        headers.append("set-cookie", cookie.output(header="").strip())
