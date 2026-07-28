import asyncio
import unittest
from unittest.mock import patch

from services.i18n import get_current_locale
from services.locale_middleware import LocaleMiddleware


async def _call_middleware(*, headers=None, session=None):
    observed = {}

    async def endpoint(scope, receive, send):
        observed["locale"] = scope["state"]["locale"]
        observed["context_locale"] = get_current_locale()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/example",
        "headers": headers or [],
        "session": session if session is not None else {},
    }
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await LocaleMiddleware(endpoint)(scope, receive, send)
    response_start = messages[0]
    response_headers = {
        key.decode("latin-1"): value.decode("latin-1")
        for key, value in response_start["headers"]
    }
    set_cookies = [
        value.decode("latin-1")
        for key, value in response_start["headers"]
        if key.lower() == b"set-cookie"
    ]
    return observed, response_headers, set_cookies


class LocaleMiddlewareTestCase(unittest.TestCase):
    def test_accept_language_does_not_persist_automatic_choice(self):
        observed, headers, set_cookies = asyncio.run(
            _call_middleware(headers=[(b"accept-language", b"en-US,en;q=0.9")])
        )
        self.assertEqual(observed, {"locale": "en", "context_locale": "en"})
        self.assertEqual(headers["content-language"], "en")
        self.assertIn("Accept-Language", headers["vary"])
        self.assertIn("Cookie", headers["vary"])
        self.assertEqual(set_cookies, [])

    def test_explicit_session_locale_overrides_cookie_and_is_persisted(self):
        _, headers, set_cookies = asyncio.run(
            _call_middleware(
                headers=[(b"cookie", b"chatcore_locale=ja")],
                session={"preferred_locale": "en"},
            )
        )
        self.assertEqual(headers["content-language"], "en")
        self.assertTrue(any("chatcore_locale=en" in value for value in set_cookies))

    def test_saved_database_locale_overrides_cookie_and_is_cached(self):
        session = {"user_id": 7}
        with patch(
            "services.locale_middleware.get_user_preferred_locale",
            return_value="en",
        ):
            observed, _, set_cookies = asyncio.run(
                _call_middleware(
                    headers=[(b"cookie", b"chatcore_locale=ja")],
                    session=session,
                )
            )
        self.assertEqual(observed["locale"], "en")
        self.assertEqual(session["preferred_locale"], "en")
        self.assertTrue(session["_preferred_locale_loaded"])
        self.assertTrue(any("chatcore_locale=en" in value for value in set_cookies))

    def test_cookie_overrides_accept_language_without_reissuing_cookie(self):
        observed, _, set_cookies = asyncio.run(
            _call_middleware(
                headers=[
                    (b"cookie", b"chatcore_locale=ja"),
                    (b"accept-language", b"en-US"),
                ]
            )
        )
        self.assertEqual(observed["locale"], "ja")
        self.assertEqual(set_cookies, [])

    def test_database_failure_falls_back_to_cookie(self):
        with self.assertLogs("services.locale_middleware", level="ERROR"):
            with patch(
                "services.locale_middleware.get_user_preferred_locale",
                side_effect=RuntimeError("db unavailable"),
            ):
                observed, _, _ = asyncio.run(
                    _call_middleware(
                        headers=[(b"cookie", b"chatcore_locale=en")],
                        session={"user_id": 7},
                    )
                )
        self.assertEqual(observed["locale"], "en")


if __name__ == "__main__":
    unittest.main()
