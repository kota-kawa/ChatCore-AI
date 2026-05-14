import asyncio
import unittest
from http.cookies import SimpleCookie
from unittest.mock import patch

from itsdangerous import URLSafeSerializer
from starlette.datastructures import MutableHeaders

from services.session_middleware import (
    REDIS_BACKEND,
    SESSION_IDS_TO_DELETE_SCOPE_KEY,
    PermanentSessionMiddleware,
)


class DummyRedis:
    def __init__(self):
        self.store = {}
        self.expiry = {}

    def ping(self):
        return True

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        if ex is not None:
            self.expiry[key] = ex
        return True

    def delete(self, key):
        if key in self.store:
            del self.store[key]
            return 1
        return 0


class FailingRedis(DummyRedis):
    def set(self, key, value, ex=None):
        raise RuntimeError("redis down on set")


def make_scope(cookie_header=None):
    headers = []
    if cookie_header:
        headers.append((b"cookie", cookie_header.encode("latin-1")))
    return {
        "type": "http",
        "asgi": {"spec_version": "2.3", "version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }


async def receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def get_session_cookie(messages):
    header_values = [
        value.decode("latin-1")
        for message in messages
        if message["type"] == "http.response.start"
        for key, value in message["headers"]
        if key.lower() == b"set-cookie"
    ]
    if not header_values:
        raise AssertionError("session cookie was not set")

    cookie = SimpleCookie()
    cookie.load(header_values[0])
    return cookie["session"].value


class RedisSessionMiddlewareTest(unittest.TestCase):
    def test_session_roundtrip_via_redis(self):
        dummy_redis = DummyRedis()
        captured = {}

        async def app(scope, receive, send):
            scope["session"]["foo"] = "bar"
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        with patch("services.session_middleware.get_redis_client", return_value=dummy_redis):
            middleware = PermanentSessionMiddleware(app, secret_key="secret", max_age=60)
            messages = []

            async def send(message):
                messages.append(message)

            asyncio.run(middleware(make_scope(), receive, send))

        signed = get_session_cookie(messages)
        serializer = URLSafeSerializer("secret", salt="strike.session")
        payload = serializer.loads(signed)
        self.assertEqual(payload["backend"], REDIS_BACKEND)

        session_id = payload["id"]
        redis_payload = dummy_redis.get(f"session:{session_id}")
        self.assertIn('"foo": "bar"', redis_payload)

        async def app_read(scope, receive, send):
            captured["session"] = dict(scope["session"])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        with patch("services.session_middleware.get_redis_client", return_value=dummy_redis):
            middleware = PermanentSessionMiddleware(app_read, secret_key="secret", max_age=60)
            messages = []

            async def send(message):
                messages.append(message)

            asyncio.run(middleware(make_scope(f"session={signed}"), receive, send))

        self.assertEqual(captured["session"]["foo"], "bar")

    def test_session_cookie_is_cleared_when_redis_unavailable(self):
        async def app(scope, receive, send):
            scope["session"]["foo"] = "bar"
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        with patch("services.session_middleware.get_redis_client", return_value=None):
            middleware = PermanentSessionMiddleware(app, secret_key="secret", max_age=60)
            messages = []

            async def send(message):
                messages.append(message)

            asyncio.run(middleware(make_scope(), receive, send))

        header_values = [
            value.decode("latin-1")
            for message in messages
            if message["type"] == "http.response.start"
            for key, value in message["headers"]
            if key.lower() == b"set-cookie"
        ]
        self.assertEqual(len(header_values), 1)
        cookie = SimpleCookie()
        cookie.load(header_values[0])
        # No session data may be embedded in the cookie when Redis is down;
        # instead the cookie must be cleared to force re-authentication.
        self.assertEqual(cookie["session"].value, "")
        self.assertEqual(cookie["session"]["max-age"], "0")

    def test_session_cookie_is_cleared_when_redis_write_fails(self):
        async def app(scope, receive, send):
            scope["session"]["foo"] = "bar"
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        with patch("services.session_middleware.get_redis_client", return_value=FailingRedis()):
            middleware = PermanentSessionMiddleware(app, secret_key="secret", max_age=60)
            messages = []

            async def send(message):
                messages.append(message)

            asyncio.run(middleware(make_scope(), receive, send))

        header_values = [
            value.decode("latin-1")
            for message in messages
            if message["type"] == "http.response.start"
            for key, value in message["headers"]
            if key.lower() == b"set-cookie"
        ]
        self.assertEqual(len(header_values), 1)
        cookie = SimpleCookie()
        cookie.load(header_values[0])
        self.assertEqual(cookie["session"].value, "")
        self.assertEqual(cookie["session"]["max-age"], "0")

    def test_legacy_cookie_backed_session_is_rejected(self):
        # A cookie minted by the old cookie-fallback path must be ignored: its
        # contents (verification codes, is_admin, etc.) are signed but not
        # encrypted, so we treat any such cookie as expired.
        serializer = URLSafeSerializer("secret", salt="strike.session")
        legacy_cookie = serializer.dumps(
            {"backend": "cookie", "data": {"verification_code": "123456", "is_admin": True}}
        )

        captured = {}

        async def app(scope, receive, send):
            captured["session"] = dict(scope["session"])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        with patch("services.session_middleware.get_redis_client", return_value=DummyRedis()):
            middleware = PermanentSessionMiddleware(app, secret_key="secret", max_age=60)
            messages = []

            async def send(message):
                messages.append(message)

            asyncio.run(
                middleware(make_scope(f"session={legacy_cookie}"), receive, send)
            )

        # Only the CSRF token may be present; the legacy payload must not leak in.
        self.assertNotIn("verification_code", captured["session"])
        self.assertNotIn("is_admin", captured["session"])

    def test_session_cookie_can_use_samesite_none_with_secure(self):
        async def app(scope, receive, send):
            scope["session"]["foo"] = "bar"
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        with patch("services.session_middleware.get_redis_client", return_value=None):
            middleware = PermanentSessionMiddleware(
                app,
                secret_key="secret",
                max_age=60,
                same_site="none",
                https_only=True,
            )
            messages = []

            async def send(message):
                messages.append(message)

            asyncio.run(middleware(make_scope(), receive, send))

        header_values = [
            value.decode("latin-1")
            for message in messages
            if message["type"] == "http.response.start"
            for key, value in message["headers"]
            if key.lower() == b"set-cookie"
        ]
        self.assertEqual(len(header_values), 1)
        cookie_header = header_values[0].lower()
        self.assertIn("samesite=none", cookie_header)
        self.assertIn("secure", cookie_header)

    def test_commit_session_deletes_rotated_session_id(self):
        dummy_redis = DummyRedis()
        dummy_redis.set("session:old-session", '{"foo": "stale"}')
        middleware = PermanentSessionMiddleware(lambda *_: None, secret_key="secret", max_age=60)
        message = {"type": "http.response.start", "headers": []}
        headers = MutableHeaders(scope=message)
        scope = {
            "session": {"foo": "fresh"},
            "session_id": None,
            SESSION_IDS_TO_DELETE_SCOPE_KEY: {"old-session"},
        }

        with patch("services.session_middleware.get_redis_client", return_value=dummy_redis):
            middleware.inner._commit_session(scope, headers)

        self.assertIsNone(dummy_redis.get("session:old-session"))
        self.assertIsInstance(scope["session_id"], str)
        self.assertNotEqual(scope["session_id"], "old-session")
        self.assertIn('"foo": "fresh"', dummy_redis.get(f"session:{scope['session_id']}"))


if __name__ == "__main__":
    unittest.main()
