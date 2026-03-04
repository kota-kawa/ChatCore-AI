from __future__ import annotations

import json
import secrets
from http.cookies import SimpleCookie
from typing import Any

from itsdangerous import BadSignature, URLSafeSerializer
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from services.cache import get_redis_client
from services.csrf import CSRF_SESSION_KEY

HeaderCollection = list[tuple[bytes, bytes]] | tuple[tuple[bytes, bytes], ...]


class PermanentSessionMiddleware:
    # Redis が使える場合は Redis セッション、未設定時は標準 SessionMiddleware に委譲する
    # Delegate to Redis-backed middleware when available, otherwise use SessionMiddleware.
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
    ) -> None:
        self.session_cookie = session_cookie
        self._use_redis = get_redis_client() is not None
        if self._use_redis:
            self.inner = RedisSessionMiddleware(
                app,
                secret_key=secret_key,
                session_cookie=session_cookie,
                max_age=max_age,
                path=path,
                same_site=same_site,
                https_only=https_only,
            )
        else:
            self.inner = SessionMiddleware(
                app,
                secret_key=secret_key,
                session_cookie=session_cookie,
                max_age=max_age,
                path=path,
                same_site=same_site,
                https_only=https_only,
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._use_redis:
            if scope["type"] != "http":
                return await self.inner(scope, receive, send)

            async def send_wrapper(message: Message) -> None:
                if message["type"] == "http.response.start":
                    session = scope.get("session") or {}
                    is_permanent = session.get("_permanent") is True
                    if session and not is_permanent:
                        # 永続化フラグがないセッションはブラウザセッション化するため期限属性を除去する
                        # Strip expiry attributes so non-permanent sessions become browser-session cookies.
                        message["headers"] = _strip_cookie_headers(
                            message["headers"], self.session_cookie
                        )
                await send(message)

            return await self.inner(scope, receive, send_wrapper)

        return await self.inner(scope, receive, send)


class RedisSessionMiddleware:
    # セッション実体は Redis に保持し、Cookie には署名付き session_id のみ保存する
    # Store session payload in Redis and keep only signed session_id in the cookie.
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
    ) -> None:
        self.app = app
        self.session_cookie = session_cookie
        self.max_age = max_age
        self.path = path
        self.same_site = same_site
        self.https_only = https_only
        self.serializer = URLSafeSerializer(secret_key, salt="strike.session")
        self.redis = get_redis_client()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # リクエスト受信時に Cookie から session_id を復元し、Redis からセッションを読み込む
        # Restore session_id from cookie and hydrate session data from Redis on request start.
        session_id = self._load_session_id(scope)
        session_data = (
            await run_in_threadpool(self._load_session, session_id)
            if session_id
            else {}
        )
        if CSRF_SESSION_KEY not in session_data:
            session_data[CSRF_SESSION_KEY] = secrets.token_urlsafe(32)
        scope["session"] = session_data
        scope["session_id"] = session_id

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                # レスポンス直前に session の保存・削除と Cookie 更新を反映する
                # Persist/delete session and update cookie right before sending response headers.
                await run_in_threadpool(self._commit_session, scope, headers)
            await send(message)

        return await self.app(scope, receive, send_wrapper)

    def _load_session_id(self, scope: Scope) -> str | None:
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
            return self.serializer.loads(signed_value)
        except BadSignature:
            return None

    def _load_session(self, session_id: str) -> dict[str, Any]:
        if self.redis is None:
            return {}
        payload = self.redis.get(self._redis_key(session_id))
        if not payload:
            return {}
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {}

    def _commit_session(self, scope: Scope, headers: MutableHeaders) -> None:
        session = scope.get("session") or {}
        session_id = scope.get("session_id")

        if not session:
            if session_id:
                # セッションが空になったら Redis と Cookie の両方を削除する
                # Remove both Redis state and cookie when session becomes empty.
                self._delete_session(session_id)
                self._set_cookie(headers, "", max_age=0)
            return

        if not session_id:
            session_id = secrets.token_urlsafe(32)
            scope["session_id"] = session_id

        self._save_session(session_id, session)

        is_permanent = session.get("_permanent") is True
        cookie_max_age = self.max_age if is_permanent else None
        self._set_cookie(headers, self.serializer.dumps(session_id), cookie_max_age)

    def _save_session(self, session_id: str, session: dict[str, Any]) -> None:
        if self.redis is None:
            return
        payload = json.dumps(session, ensure_ascii=False)
        if self.max_age is not None:
            self.redis.set(self._redis_key(session_id), payload, ex=self.max_age)
        else:
            self.redis.set(self._redis_key(session_id), payload)

    def _delete_session(self, session_id: str) -> None:
        if self.redis is None:
            return
        self.redis.delete(self._redis_key(session_id))

    def _redis_key(self, session_id: str) -> str:
        return f"session:{session_id}"

    def _set_cookie(
        self, headers: MutableHeaders, value: str, max_age: int | None = None
    ) -> None:
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


def _strip_cookie_headers(headers: HeaderCollection, cookie_name: str) -> HeaderCollection:
    # 既存 Set-Cookie を走査し、対象 Cookie の期限属性だけを除去したヘッダを再構築する
    # Rebuild Set-Cookie headers while stripping only expiry attributes for the target cookie.
    new_headers: list[tuple[bytes, bytes]] = []
    set_cookie_headers: list[str] = []

    for key, value in headers:
        if key.lower() == b"set-cookie":
            set_cookie_headers.append(value.decode("latin-1"))
        else:
            new_headers.append((key, value))

    if not set_cookie_headers:
        return headers

    for cookie in set_cookie_headers:
        if cookie.startswith(f"{cookie_name}="):
            cookie = _strip_cookie_attributes(cookie)
        new_headers.append((b"set-cookie", cookie.encode("latin-1")))

    return new_headers


def _strip_cookie_attributes(cookie: str) -> str:
    # Max-Age / Expires を除外し、他属性（Path, HttpOnly, SameSite など）は維持する
    # Drop Max-Age/Expires while keeping other attributes such as Path/HttpOnly/SameSite.
    parts = cookie.split(";")
    if len(parts) <= 1:
        return cookie

    kept_parts = [parts[0].strip()]
    for part in parts[1:]:
        attr = part.strip()
        attr_lower = attr.lower()
        if attr_lower.startswith("max-age=") or attr_lower.startswith("expires="):
            continue
        kept_parts.append(attr)

    return "; ".join(kept_parts)
