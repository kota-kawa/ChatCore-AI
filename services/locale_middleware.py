"""リクエストごとの表示言語（ロケール）を決め、レスポンスの言語ヘッダとクッキーへ反映する ASGI ミドルウェア。

セッション、ユーザー設定、クッキー、Accept-Language の順に判定し、現在のロケールを `services.i18n` のコンテキストへ設定する。
ASGI middleware that decides each request's display locale and reflects it in the response language headers and cookie.
It resolves from session, user preference, cookie, then Accept-Language, and sets the current locale in the `services.i18n` context.
"""

from __future__ import annotations

import inspect
import logging
from http.cookies import CookieError, SimpleCookie
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from services.chat_service import get_user_preferred_locale
from services.i18n import (
    LOCALE_COOKIE_NAME,
    PREFERRED_LOCALE_LOADED_SESSION_KEY,
    PREFERRED_LOCALE_SESSION_KEY,
    Locale,
    normalize_locale,
    parse_accept_language,
    reset_current_locale,
    set_current_locale,
)

LOCALE_COOKIE_MAX_AGE_SECONDS = 365 * 24 * 60 * 60
logger = logging.getLogger(__name__)


async def _await_result(value: Any) -> Any:
    # 同期関数でもコルーチンでも、呼び出し側が同じ書き方で結果を受け取れるようにする。
    # Let callers receive the result the same way whether the function is sync or a coroutine.
    if inspect.isawaitable(value):
        return await value
    return value


def _append_vary(headers: MutableHeaders, name: str) -> None:
    # 既存の Vary を壊さず、まだ無い場合だけ項目を足す（言語で応答が変わるためキャッシュを分けさせる）。
    # Add the name to Vary only when absent, keeping existing entries, so caches key responses by language.
    existing = headers.get("vary", "")
    values = [item.strip() for item in existing.split(",") if item.strip()]
    lower_values = {item.lower() for item in values}
    if name.lower() not in lower_values:
        values.append(name)
    headers["vary"] = ", ".join(values)


def _locale_cookie_header(
    locale: Locale,
    *,
    same_site: str = "lax",
    https_only: bool = False,
) -> str:
    # ロケール用 Set-Cookie ヘッダ値を作る。
    # Build the Set-Cookie header value for the locale cookie.
    cookie = SimpleCookie()
    cookie[LOCALE_COOKIE_NAME] = locale
    cookie[LOCALE_COOKIE_NAME]["path"] = "/"
    cookie[LOCALE_COOKIE_NAME]["max-age"] = str(LOCALE_COOKIE_MAX_AGE_SECONDS)
    if same_site:
        cookie[LOCALE_COOKIE_NAME]["samesite"] = same_site
    if https_only:
        cookie[LOCALE_COOKIE_NAME]["secure"] = True
    return cookie.output(header="").strip()


def _response_sets_locale_cookie(headers: MutableHeaders) -> bool:
    # ハンドラが既にロケールのクッキーを設定済みか調べ、二重に Set-Cookie を付けないようにする。
    # Check whether the handler already set the locale cookie, so a second Set-Cookie is not added.
    prefix = f"{LOCALE_COOKIE_NAME}=".lower()
    return any(value.lower().startswith(prefix) for value in headers.getlist("set-cookie"))


def set_locale_cookie(
    response: Response,
    locale: Any,
    *,
    same_site: str = "lax",
    https_only: bool = False,
) -> None:
    """ロケールのクッキーをレスポンスに設定する。未対応のロケールは ValueError。

    Set the locale cookie on the response; raises ValueError for an unsupported locale.
    """
    normalized = normalize_locale(locale)
    if normalized is None:
        raise ValueError("Unsupported locale")
    response.set_cookie(
        LOCALE_COOKIE_NAME,
        normalized,
        max_age=LOCALE_COOKIE_MAX_AGE_SECONDS,
        path="/",
        secure=https_only,
        httponly=False,
        samesite=same_site,
    )


class LocaleMiddleware:
    """リクエストのロケールを決めて現在のロケールに設定し、応答へ Content-Language と必要ならクッキーを付ける。

    Resolve the request locale, set it as the current locale, and add Content-Language (and the cookie when needed) to the response.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        same_site: str = "lax",
        https_only: bool = False,
        bypass_paths: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.same_site = same_site
        self.https_only = https_only
        self.bypass_paths = tuple(bypass_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # HTTP 以外と bypass_paths のパスはロケール処理を行わず、そのまま内側へ渡す。
        # Pass non-HTTP scopes and bypass_paths straight through without locale handling.
        if scope["type"] != "http" or str(scope.get("path") or "") in self.bypass_paths:
            await self.app(scope, receive, send)
            return

        locale, persist_cookie = await self._resolve_locale(scope)
        state = scope.setdefault("state", {})
        state["locale"] = locale
        state["persist_locale_cookie"] = persist_cookie
        token = set_current_locale(locale)

        async def send_wrapper(message: Message) -> None:
            # 応答開始時に、ハンドラが state で書き換えたロケールも反映してヘッダを付ける。
            # On response start, add headers using the locale the handler may have changed in state.
            if message["type"] == "http.response.start":
                response_locale = normalize_locale(state.get("locale"), default=locale) or locale
                headers = MutableHeaders(scope=message)
                headers["content-language"] = response_locale
                _append_vary(headers, "Accept-Language")
                _append_vary(headers, "Cookie")
                request_cookies = self._cookies_from_scope(scope)
                # セッションやユーザー設定由来で、クッキーが現在の言語と食い違うときだけクッキーを更新する。
                # Refresh the cookie only when the locale came from session/preference and the cookie differs.
                if (
                    state.get("persist_locale_cookie") is True
                    and normalize_locale(request_cookies.get(LOCALE_COOKIE_NAME)) != response_locale
                    and not _response_sets_locale_cookie(headers)
                ):
                    headers.append(
                        "set-cookie",
                        _locale_cookie_header(
                            response_locale,
                            same_site=self.same_site,
                            https_only=self.https_only,
                        ),
                    )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            reset_current_locale(token)

    async def _resolve_locale(self, scope: Scope) -> tuple[Locale, bool]:
        # 優先順位は、セッションの言語、ログインユーザーの保存済み設定、クッキー、Accept-Language の順。
        # 戻り値の bool は、クッキーへ書き戻すべきか（セッション/設定由来なら True）。
        # Priority: session locale, the signed-in user's stored preference, cookie, then Accept-Language.
        # The bool says whether the locale should be written back to the cookie (True for session/preference).
        session = scope.get("session")
        if isinstance(session, dict):
            session_locale = normalize_locale(session.get(PREFERRED_LOCALE_SESSION_KEY))
            if session_locale is not None:
                return session_locale, True

            user_id = session.get("user_id")
            # ユーザー設定の DB 参照はセッションにつき一度だけ行い、結果（設定なしも）を LOADED フラグで記録する。
            # Look up the stored preference only once per session; the LOADED flag records it even when none is set.
            if user_id and session.get(PREFERRED_LOCALE_LOADED_SESSION_KEY) is not True:
                try:
                    preferred_locale = await _await_result(
                        get_user_preferred_locale(int(user_id))
                    )
                except Exception:
                    logger.exception("Failed to load the authenticated user's locale preference.")
                else:
                    session[PREFERRED_LOCALE_LOADED_SESSION_KEY] = True
                    if preferred_locale is not None:
                        session[PREFERRED_LOCALE_SESSION_KEY] = preferred_locale
                        return preferred_locale, True

        cookies = self._cookies_from_scope(scope)
        cookie_locale = normalize_locale(cookies.get(LOCALE_COOKIE_NAME))
        if cookie_locale is not None:
            return cookie_locale, False
        return parse_accept_language(Headers(scope=scope).get("accept-language")), False

    @staticmethod
    def _cookies_from_scope(scope: Scope) -> dict[str, str]:
        # Cookie ヘッダを辞書にする。壊れたヘッダは空として扱う。
        # Parse the Cookie header into a dict, treating a malformed header as empty.
        cookie_header = Headers(scope=scope).get("cookie")
        if not cookie_header:
            return {}
        cookies = SimpleCookie()
        try:
            cookies.load(cookie_header)
        except CookieError:
            return {}
        return {key: morsel.value for key, morsel in cookies.items()}
