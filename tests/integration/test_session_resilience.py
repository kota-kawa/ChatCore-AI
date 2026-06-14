import asyncio
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Request
from itsdangerous import URLSafeSerializer

from services.auth_session import establish_authenticated_session
from services.session_middleware import REDIS_BACKEND, PermanentSessionMiddleware


# 日本語: DummyRedis に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to DummyRedis.
class DummyRedis:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, *, fail_on_set: bool = False):
        self.fail_on_set = fail_on_set
        self.store = {}

    # 日本語: ping に関する処理の入口です。
    # English: Entry point for logic related to ping.
    def ping(self):
        return True

    # 日本語: get の取得処理を担当します。
    # English: Handle fetching for get.
    def get(self, key):
        return self.store.get(key)

    # 日本語: set の設定処理を担当します。
    # English: Handle setting for set.
    def set(self, key, value, ex=None):
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self.fail_on_set:
            raise RuntimeError("redis write failed")
        self.store[key] = value
        return True

    # 日本語: delete の削除処理を担当します。
    # English: Handle deleting for delete.
    def delete(self, key):
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if key in self.store:
            del self.store[key]
            return 1
        return 0


# 日本語: build test app の組み立て処理を担当します。
# English: Handle building for build test app.
def build_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        PermanentSessionMiddleware,
        secret_key="integration-session-secret",
        max_age=120,
    )

    # 日本語: set session values の設定処理を非同期で担当します。
    # English: Handle setting for set session values asynchronously.
    @app.post("/session/set")
    async def set_session_values(request: Request):
        payload = await request.json()
        # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
        # English: Process each target item in order and accumulate the needed result.
        for key, value in payload.items():
            request.session[key] = value
        return {"status": "ok"}

    # 日本語: read session values の読み込み処理を非同期で担当します。
    # English: Handle reading for read session values asynchronously.
    @app.get("/session/read")
    async def read_session_values(request: Request):
        return {
            "session": dict(request.session),
            "session_id": request.scope.get("session_id"),
        }

    # 日本語: simulate login に関する処理の入口です。
    # English: Entry point for logic related to simulate login.
    @app.post("/session/login")
    async def simulate_login(request: Request):
        establish_authenticated_session(request, user_id=42, email="user@example.com")
        return {"status": "ok"}

    return app


# 日本語: SessionResilienceIntegrationTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to SessionResilienceIntegrationTestCase.
class SessionResilienceIntegrationTestCase(unittest.TestCase):
    # 日本語: setUp に関する処理の入口です。
    # English: Entry point for logic related to setUp.
    def setUp(self):
        self.app = build_test_app()
        self.serializer = URLSafeSerializer("integration-session-secret", salt="strike.session")

    # 日本語: make client の生成処理を担当します。
    # English: Handle creating for make client.
    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
            follow_redirects=True,
        )

    # 日本語: decode session cookie に関する処理の入口です。
    # English: Entry point for logic related to decode session cookie.
    def _decode_session_cookie(self, response: httpx.Response) -> dict:
        signed = response.cookies.get("session")
        self.assertIsNotNone(signed)
        return self.serializer.loads(signed)

    # 日本語: test login rotates session id and deletes old redis session のテスト検証を担当します。
    # English: Handle verifying test behavior for test login rotates session id and deletes old redis session.
    def test_login_rotates_session_id_and_deletes_old_redis_session(self):
        # 日本語: scenario に関する処理の入口です。
        # English: Entry point for logic related to scenario.
        async def scenario():
            redis_client = DummyRedis()
            # 日本語: 必要なリソースやコンテキストを限定して利用します。
            # English: Use the required resource or context within this limited block.
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

    # 日本語: test session is cleared when redis is unavailable のテスト検証を担当します。
    # English: Handle verifying test behavior for test session is cleared when redis is unavailable.
    def test_session_is_cleared_when_redis_is_unavailable(self):
        # 日本語: scenario に関する処理の入口です。
        # English: Entry point for logic related to scenario.
        async def scenario():
            # 日本語: 必要なリソースやコンテキストを限定して利用します。
            # English: Use the required resource or context within this limited block.
            with patch("services.session_middleware.get_redis_client", return_value=None):
                async with self._make_client() as client:
                    set_response = await client.post("/session/set", json={"foo": "bar"})
                    # No session cookie may carry the data — Redis being down
                    # must clear the cookie rather than persist secrets in it.
                    cookie_value = set_response.cookies.get("session")
                    self.assertIn(cookie_value, (None, ""))

                    read_response = await client.get("/session/read")

            self.assertEqual(read_response.status_code, 200)
            self.assertNotIn("foo", read_response.json()["session"])

        asyncio.run(scenario())

    # 日本語: test session is cleared when redis write fails のテスト検証を担当します。
    # English: Handle verifying test behavior for test session is cleared when redis write fails.
    def test_session_is_cleared_when_redis_write_fails(self):
        # 日本語: scenario に関する処理の入口です。
        # English: Entry point for logic related to scenario.
        async def scenario():
            # 日本語: 必要なリソースやコンテキストを限定して利用します。
            # English: Use the required resource or context within this limited block.
            with patch(
                "services.session_middleware.get_redis_client",
                return_value=DummyRedis(fail_on_set=True),
            ):
                async with self._make_client() as client:
                    set_response = await client.post("/session/set", json={"foo": "bar"})
                    cookie_value = set_response.cookies.get("session")

            self.assertEqual(set_response.status_code, 200)
            self.assertIn(cookie_value, (None, ""))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
