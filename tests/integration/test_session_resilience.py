import asyncio
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Request
from itsdangerous import URLSafeSerializer

from services.auth_session import establish_authenticated_session
from services.session_middleware import COOKIE_BACKEND, REDIS_BACKEND, PermanentSessionMiddleware


class DummyRedis:
    def __init__(self, *, fail_on_set: bool = False):
        self.fail_on_set = fail_on_set
        self.store = {}

    def ping(self):
        return True

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        if self.fail_on_set:
            raise RuntimeError("redis write failed")
        self.store[key] = value
        return True

    def delete(self, key):
        if key in self.store:
            del self.store[key]
            return 1
        return 0


def build_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        PermanentSessionMiddleware,
        secret_key="integration-session-secret",
        max_age=120,
    )

    @app.post("/session/set")
    async def set_session_values(request: Request):
        payload = await request.json()
        for key, value in payload.items():
            request.session[key] = value
        return {"status": "ok"}

    @app.get("/session/read")
    async def read_session_values(request: Request):
        return {
            "session": dict(request.session),
            "session_id": request.scope.get("session_id"),
        }

    @app.post("/session/login")
    async def simulate_login(request: Request):
        establish_authenticated_session(request, user_id=42, email="user@example.com")
        return {"status": "ok"}

    return app


class SessionResilienceIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = build_test_app()
        self.serializer = URLSafeSerializer("integration-session-secret", salt="strike.session")

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
            follow_redirects=True,
        )

    def _decode_session_cookie(self, response: httpx.Response) -> dict:
        signed = response.cookies.get("session")
        self.assertIsNotNone(signed)
        return self.serializer.loads(signed)

    def test_login_rotates_session_id_and_deletes_old_redis_session(self):
        async def scenario():
            redis_client = DummyRedis()
            with patch("services.session_middleware.get_redis_client", return_value=redis_client):
                async with self._make_client() as client:
                    before_login = await client.post("/session/set", json={"pre_auth": "value"})
                    before_payload = self._decode_session_cookie(before_login)
                    self.assertEqual(before_payload["backend"], REDIS_BACKEND)
                    old_session_id = before_payload["id"]
                    self.assertIsNotNone(redis_client.get(f"session:{old_session_id}"))

                    login_response = await client.post("/session/login")
                    after_payload = self._decode_session_cookie(login_response)
                    self.assertEqual(after_payload["backend"], REDIS_BACKEND)
                    new_session_id = after_payload["id"]
                    self.assertNotEqual(new_session_id, old_session_id)

                    self.assertIsNone(redis_client.get(f"session:{old_session_id}"))
                    persisted_new = redis_client.get(f"session:{new_session_id}")
                    self.assertIsNotNone(persisted_new)
                    persisted_payload = json.loads(persisted_new)
                    self.assertEqual(persisted_payload["user_id"], 42)
                    self.assertEqual(persisted_payload["user_email"], "user@example.com")
                    self.assertTrue(persisted_payload.get("_permanent"))
                    self.assertEqual(persisted_payload["pre_auth"], "value")

        asyncio.run(scenario())

    def test_session_falls_back_to_cookie_when_redis_is_unavailable(self):
        async def scenario():
            with patch("services.session_middleware.get_redis_client", return_value=None):
                async with self._make_client() as client:
                    set_response = await client.post("/session/set", json={"foo": "bar"})
                    payload = self._decode_session_cookie(set_response)
                    self.assertEqual(payload["backend"], COOKIE_BACKEND)
                    self.assertEqual(payload["data"]["foo"], "bar")

                    read_response = await client.get("/session/read")

            self.assertEqual(read_response.status_code, 200)
            self.assertEqual(read_response.json()["session"]["foo"], "bar")

        asyncio.run(scenario())

    def test_session_falls_back_to_cookie_when_redis_write_fails(self):
        async def scenario():
            with patch(
                "services.session_middleware.get_redis_client",
                return_value=DummyRedis(fail_on_set=True),
            ):
                async with self._make_client() as client:
                    set_response = await client.post("/session/set", json={"foo": "bar"})
                    payload = self._decode_session_cookie(set_response)

            self.assertEqual(set_response.status_code, 200)
            self.assertEqual(payload["backend"], COOKIE_BACKEND)
            self.assertEqual(payload["data"]["foo"], "bar")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
