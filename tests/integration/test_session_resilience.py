import asyncio
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Request
from itsdangerous import URLSafeSerializer

from services.auth_session import establish_authenticated_session
from services.session_middleware import REDIS_BACKEND, PermanentSessionMiddleware


# 日本語: テスト用のRedisクライアントのモッククラス。
# English: Mock class for the Redis client used in testing.
class DummyRedis:
    # 日本語: 初期化。書き込み失敗をシミュレートするフラグと内部ストレージを設定します。
    # English: Initialize. Sets flag to simulate write failures and the internal storage dictionary.
    def __init__(self, *, fail_on_set: bool = False):
        self.fail_on_set = fail_on_set
        self.store = {}

    # 日本語: 接続確認。常にTrueを返します。
    # English: Connection check. Always returns True.
    def ping(self):
        return True

    # 日本語: 指定キーに対応する値を取得します。
    # English: Retrieve the value corresponding to the specified key.
    def get(self, key):
        return self.store.get(key)

    # 日本語: 指定キーに対応する値を保存します。fail_on_setがTrueの場合にRuntimeErrorを発生させます。
    # English: Set the value corresponding to the specified key. Raises RuntimeError if fail_on_set is True.
    def set(self, key, value, ex=None):
        if self.fail_on_set:
            raise RuntimeError("redis write failed")
        self.store[key] = value
        return True

    # 日本語: 指定キーを削除します。
    # English: Delete the specified key.
    def delete(self, key):
        if key in self.store:
            del self.store[key]
            return 1
        return 0


# 日本語: テスト用のFastAPIアプリケーションインスタンスを構築します。
# English: Build a FastAPI application instance for testing.
def build_test_app() -> FastAPI:
    app = FastAPI()
    # 日本語: セッションミドルウェアを追加
    # English: Add session middleware
    app.add_middleware(
        PermanentSessionMiddleware,
        secret_key="integration-session-secret",
        max_age=120,
    )

    # 日本語: テスト用セッションに値を書き込むエンドポイント
    # English: Endpoint to write values to the test session
    @app.post("/session/set")
    async def set_session_values(request: Request):
        payload = await request.json()
        for key, value in payload.items():
            request.session[key] = value
        return {"status": "ok"}

    # 日本語: テスト用セッションから値を読み出すエンドポイント
    # English: Endpoint to read values from the test session
    @app.get("/session/read")
    async def read_session_values(request: Request):
        return {
            "session": dict(request.session),
            "session_id": request.scope.get("session_id"),
        }

    # 日本語: ログインのセッション確立を再現するエンドポイント
    # English: Endpoint to simulate establishing an authenticated login session
    @app.post("/session/login")
    async def simulate_login(request: Request):
        establish_authenticated_session(request, user_id=42, email="user@example.com")
        return {"status": "ok"}

    return app


# 日本語: セッションの耐障害性をテストする統合テストケースクラス。
# English: Integration test case class testing session resilience.
class SessionResilienceIntegrationTestCase(unittest.TestCase):
    # 日本語: 各テスト開始前のセットアップ。テスト用アプリとシリアライザを準備します。
    # English: Set up before each test. Prepares the test app and URLSafeSerializer.
    def setUp(self):
        self.app = build_test_app()
        self.serializer = URLSafeSerializer("integration-session-secret", salt="strike.session")

    # 日本語: テスト用アシンククライアントを作成して返却します。
    # English: Create and return an HTTPX async client for testing.
    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
            follow_redirects=True,
        )

    # 日本語: レスポンスのクッキーからセッションの中身をデコードします。
    # English: Decode the session payload from the response cookie.
    def _decode_session_cookie(self, response: httpx.Response) -> dict:
        signed = response.cookies.get("session")
        self.assertIsNotNone(signed)
        return self.serializer.loads(signed)

    # 日本語: ログイン時にセッションIDがローテーションされ、以前のRedisセッションが削除されることを検証するテスト。
    # English: Test that login rotates the session ID and deletes the old Redis session.
    def test_login_rotates_session_id_and_deletes_old_redis_session(self):
        async def scenario():
            redis_client = DummyRedis()
            with patch("services.session_middleware.get_redis_client", return_value=redis_client):
                async with self._make_client() as client:
                    # 日本語: ログイン前の初期データをセッションに保存
                    # English: Save initial data to session before login
                    before_login = await client.post("/session/set", json={"pre_auth": "value"})
                    before_payload = self._decode_session_cookie(before_login)
                    self.assertEqual(before_payload["backend"], REDIS_BACKEND)
                    old_session_id = before_payload["id"]
                    self.assertIsNotNone(redis_client.get(f"session:{old_session_id}"))

                    # 日本語: ログイン要求を送信
                    # English: Send login request
                    login_response = await client.post("/session/login")
                    after_payload = self._decode_session_cookie(login_response)
                    self.assertEqual(after_payload["backend"], REDIS_BACKEND)
                    new_session_id = after_payload["id"]
                    # 日本語: セッションIDが新しくなっていること
                    # English: Confirm session ID has changed
                    self.assertNotEqual(new_session_id, old_session_id)

                    # 日本語: 古いセッションIDのデータが削除されていること
                    # English: Confirm old session ID data is deleted
                    self.assertIsNone(redis_client.get(f"session:{old_session_id}"))
                    persisted_new = redis_client.get(f"session:{new_session_id}")
                    self.assertIsNotNone(persisted_new)
                    persisted_payload = json.loads(persisted_new)
                    self.assertEqual(persisted_payload["user_id"], 42)
                    self.assertEqual(persisted_payload["user_email"], "user@example.com")
                    self.assertTrue(persisted_payload.get("_permanent"))
                    self.assertEqual(persisted_payload["pre_auth"], "value")

        asyncio.run(scenario())

    # 日本語: Redisが利用不可である場合にセッションデータが保存されず、クッキーもクリアされることを検証するテスト。
    # English: Test that the session is cleared when Redis is unavailable.
    def test_session_is_cleared_when_redis_is_unavailable(self):
        async def scenario():
            with patch("services.session_middleware.get_redis_client", return_value=None):
                async with self._make_client() as client:
                    # 日本語: Redisに繋がらない状態でセッションに書き込もうとする
                    # English: Try writing to session with Redis down
                    set_response = await client.post("/session/set", json={"foo": "bar"})
                    cookie_value = set_response.cookies.get("session")
                    self.assertIn(cookie_value, (None, ""))

                    # 日本語: セッションの値を読み込み、書き込まれていないことを確認
                    # English: Read session values and confirm nothing was saved
                    read_response = await client.get("/session/read")

            self.assertEqual(read_response.status_code, 200)
            self.assertNotIn("foo", read_response.json()["session"])

        asyncio.run(scenario())

    # 日本語: Redisへの書き込みが失敗した際に、セッションがクリアされることを検証するテスト。
    # English: Test that the session is cleared when writing to Redis fails.
    def test_session_is_cleared_when_redis_write_fails(self):
        async def scenario():
            with patch(
                "services.session_middleware.get_redis_client",
                return_value=DummyRedis(fail_on_set=True),
            ):
                async with self._make_client() as client:
                    # 日本語: Redis書き込みエラーが発生する状態でセッションに書き込もうとする
                    # English: Try writing to session where Redis write error occurs
                    set_response = await client.post("/session/set", json={"foo": "bar"})
                    cookie_value = set_response.cookies.get("session")

            self.assertEqual(set_response.status_code, 200)
            self.assertIn(cookie_value, (None, ""))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
