from __future__ import annotations

import logging
from http.cookies import CookieError, SimpleCookie
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from services.async_utils import run_blocking
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
from services.repositories.user_preferences_repository import get_user_preferred_locale


LOCALE_COOKIE_MAX_AGE_SECONDS = 365 * 24 * 60 * 60
logger = logging.getLogger(__name__)


def _append_vary(headers: MutableHeaders, name: str) -> None:
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
    prefix = f"{LOCALE_COOKIE_NAME}=".lower()
    return any(value.lower().startswith(prefix) for value in headers.getlist("set-cookie"))


def set_locale_cookie(
    response: Response,
    locale: Any,
    *,
    same_site: str = "lax",
    https_only: bool = False,
) -> None:
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
        if scope["type"] != "http" or str(scope.get("path") or "") in self.bypass_paths:
            await self.app(scope, receive, send)
            return

        locale, persist_cookie = await self._resolve_locale(scope)
        state = scope.setdefault("state", {})
        state["locale"] = locale
        state["persist_locale_cookie"] = persist_cookie
        token = set_current_locale(locale)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_locale = normalize_locale(state.get("locale"), default=locale)
                headers = MutableHeaders(scope=message)
                headers["content-language"] = response_locale
                _append_vary(headers, "Accept-Language")
                _append_vary(headers, "Cookie")
                request_cookies = self._cookies_from_scope(scope)
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
        session = scope.get("session")
        if isinstance(session, dict):
            session_locale = normalize_locale(session.get(PREFERRED_LOCALE_SESSION_KEY))
            if session_locale is not None:
                return session_locale, True

            user_id = session.get("user_id")
            if user_id and session.get(PREFERRED_LOCALE_LOADED_SESSION_KEY) is not True:
                try:
                    preferred_locale = await run_blocking(get_user_preferred_locale, int(user_id))
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
        cookie_header = Headers(scope=scope).get("cookie")
        if not cookie_header:
            return {}
        cookies = SimpleCookie()
        try:
            cookies.load(cookie_header)
        except CookieError:
            return {}
        return {key: morsel.value for key, morsel in cookies.items()}
