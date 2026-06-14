import asyncio
import unittest
from datetime import datetime
from unittest.mock import patch

import httpx

from blueprints.auth import auth_bp
from blueprints.memo import memo_bp
from services.csrf import CSRF_HEADER_NAME, CSRF_SESSION_KEY
from services.db import Error
from tests.helpers.app_helpers import build_session_test_app


# 日本語: テスト用のアプリケーションインスタンスを構築します。authおよびmemoのブループリントを登録します。
# English: Build a test application instance registering the auth and memo blueprints.
def build_test_app():
    return build_session_test_app(
        auth_bp,
        memo_bp,
        secret_key="endpoint-test-secret",
        include_test_session_route=True,
    )


# 日本語: エンドポイントルーティング用の統合テストケースクラス。
# English: Integration test case class for endpoint routes.
class EndpointRoutesTestCase(unittest.TestCase):
    # 日本語: テスト毎の初期化処理。テスト用アプリを構築します。
    # English: Set up execution for each test. Builds the test app.
    def setUp(self):
        self.app = build_test_app()

    # 日本語: テスト用のアシンククライアントを作成して返却します。
    # English: Create and return an HTTPX async client for testing.
    def _make_client(self, *, follow_redirects=True) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
            follow_redirects=follow_redirects,
        )

    # 日本語: テスト用セッションに任意のキー・値ペアを設定します。
    # English: Set arbitrary key-value pairs in the test session.
    async def _set_session(self, client: httpx.AsyncClient, values):
        response = await client.post("/_test/session", json=values)
        self.assertEqual(response.status_code, 200)

    # 日本語: CSRFトークンをヘッダーおよびセッションに設定した上でPOSTリクエストを送信します。
    # English: Send a POST request after setting the CSRF token in both headers and session.
    async def _post_with_csrf(self, client: httpx.AsyncClient, path, *, json):
        csrf_token = "test-csrf-token"
        # 日本語: セッションにCSRFトークンを設定
        # English: Set CSRF token in session
        await self._set_session(client, {CSRF_SESSION_KEY: csrf_token})
        # 日本語: CSRFヘッダーを含めてリクエストを送信
        # English: Send request with CSRF header included
        return await client.post(path, json=json, headers={CSRF_HEADER_NAME: csrf_token})

    # 日本語: ログアウト状態での現在ユーザー取得APIエンドポイントのテスト。
    # English: Test the current user endpoint when the user is logged out.
    def test_current_user_endpoint_when_logged_out(self):
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                response = await client.get("/api/current_user")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"logged_in": False})

        asyncio.run(scenario())

    # 日本語: ログイン状態での現在ユーザー取得APIエンドポイントのテスト。
    # English: Test the current user endpoint when the user is logged in.
    def test_current_user_endpoint_when_logged_in(self):
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                # 日本語: セッションにユーザーIDを設定
                # English: Set user_id in session
                await self._set_session(client, {"user_id": 7})
                with patch(
                    "blueprints.auth.get_user_by_id",
                    return_value={"id": 7, "email": "user@example.com"},
                ):
                    response = await client.get("/api/current_user")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["logged_in"])
            self.assertEqual(payload["user"]["id"], 7)
            self.assertEqual(payload["user"]["email"], "user@example.com")

        asyncio.run(scenario())

    # 日本語: ログアウト時にセッションが破棄され、ログイン画面にリダイレクトされるかのテスト。
    # English: Test that logout clears the session and redirects to the login page.
    def test_logout_endpoint_clears_session_and_redirects(self):
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client(follow_redirects=False) as client:
                csrf_token = "logout-csrf-token"
                # 日本語: ログイン済みの状態としてセッションを設定
                # English: Set up the session as a logged-in state
                await self._set_session(
                    client,
                    {
                        "user_id": 7,
                        "user_email": "user@example.com",
                        CSRF_SESSION_KEY: csrf_token,
                    },
                )
                # 日本語: ログアウトエンドポイントへPOST
                # English: POST to the logout endpoint
                response = await client.post(
                    "/logout",
                    headers={CSRF_HEADER_NAME: csrf_token},
                )
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.headers["location"].endswith("/login"))

                # 日本語: ログアウト後のユーザー状態を確認
                # English: Check user status after logout
                current_user = await client.get("/api/current_user")

            self.assertEqual(current_user.status_code, 200)
            self.assertEqual(current_user.json(), {"logged_in": False})

        asyncio.run(scenario())

    # 日本語: 最近のメモ取得APIエンドポイントがシリアライズされたメモ一覧を返すかのテスト。
    # English: Test that the recent memos endpoint returns serialized memos.
    def test_memo_recent_endpoint_returns_serialized_memos(self):
        async def scenario():
            sample = {
                "id": 1,
                "title": "サンプル",
                "created_at": datetime(2024, 1, 1, 9, 30),
                "ai_response": "response",
            }

            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                # 日本語: セッションにユーザーIDを設定
                # English: Set user_id in session
                await self._set_session(client, {"user_id": 7})
                with patch(
                    "blueprints.memo._fetch_memo_summaries",
                    return_value={"total": 1, "memos": [{"id": sample["id"], "title": sample["title"], "created_at": "2024-01-01T09:30:00"}]},
                ):
                    response = await client.get("/memo/api/recent?limit=5")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["memos"][0]["id"], 1)
            self.assertEqual(payload["memos"][0]["created_at"], "2024-01-01T09:30:00")

        asyncio.run(scenario())

    # 日本語: ログインしていない場合に最近のメモ取得APIがエラーを返すかのテスト。
    # English: Test that the recent memos endpoint requires authentication.
    def test_memo_recent_endpoint_requires_login(self):
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                response = await client.get("/memo/api/recent?limit=5")

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {"status": "fail", "error": "ログインが必要です"})

        asyncio.run(scenario())

    # 日本語: メモ作成APIが必要なバリデーションエラーを検知するかのテスト。
    # English: Test that the memo creation endpoint validates required fields.
    def test_memo_create_endpoint_validates_required_fields(self):
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                # 日本語: セッションにユーザーIDを設定
                # English: Set user_id in session
                await self._set_session(client, {"user_id": 7})
                # 日本語: 空のAIレスポンスを指定してリクエストを送信
                # English: Send request with an empty AI response
                response = await self._post_with_csrf(
                    client,
                    "/memo/api",
                    json={"ai_response": ""},
                )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["status"], "fail")

        asyncio.run(scenario())

    # 日本語: メモ作成に成功した場合の正常系テスト。
    # English: Test that creating a memo succeeds with correct inputs.
    def test_memo_create_endpoint_success(self):
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                # 日本語: セッションにユーザーIDを設定
                # English: Set user_id in session
                await self._set_session(client, {"user_id": 7})
                with patch("blueprints.memo._insert_memo", return_value=42):
                    response = await self._post_with_csrf(
                        client,
                        "/memo/api",
                        json={
                            "ai_response": "ok",
                            "title": "",
                        },
                    )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["memo_id"], 42)

        asyncio.run(scenario())

    # 日本語: ログインしていない場合にメモ作成APIがエラーを返すかのテスト。
    # English: Test that memo creation requires authentication.
    def test_memo_create_endpoint_requires_login(self):
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                response = await self._post_with_csrf(
                    client,
                    "/memo/api",
                    json={"ai_response": "ok"},
                )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {"status": "fail", "error": "ログインが必要です"})

        asyncio.run(scenario())

    # 日本語: データベース読み込み失敗時に最近のメモ取得APIが空リストにフォールバックするかのテスト。
    # English: Test that the recent memos endpoint falls back to empty values when db read fails.
    def test_memo_recent_endpoint_falls_back_to_empty_when_db_read_fails(self):
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                # 日本語: セッションにユーザーIDを設定
                # English: Set user_id in session
                await self._set_session(client, {"user_id": 7})
                # 日本語: DBコネクション取得時にエラーを発生させる
                # English: Raise error when obtaining DB connection
                with patch("blueprints.memo.get_db_connection", side_effect=Error("db down")):
                    response = await client.get("/memo/api/recent?limit=5")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"memos": [], "total": 0})

        asyncio.run(scenario())

    # 日本語: 並行リクエスト環境下において、データベース接続失敗時の挙動が安定しているかのテスト。
    # English: Test that concurrent DB connection failure is handled stably.
    def test_memo_recent_endpoint_db_failure_is_stable_under_concurrency(self):
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                # 日本語: セッションにユーザーIDを設定
                # English: Set user_id in session
                await self._set_session(client, {"user_id": 7})
                with patch("blueprints.memo.get_db_connection", side_effect=Error("db down")):
                    # 日本語: 並行してリクエストを実行
                    # English: Run requests concurrently
                    responses = await asyncio.gather(
                        client.get("/memo/api/recent?limit=5"),
                        client.get("/memo/api/recent?limit=5"),
                        client.get("/memo/api/recent?limit=5"),
                        client.get("/memo/api/recent?limit=5"),
                    )

            for response in responses:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"memos": [], "total": 0})

        asyncio.run(scenario())

    # 日本語: DBトランザクション失敗時にメモ作成APIが500エラーを返すかのテスト。
    # English: Test that the memo creation endpoint returns a 500 code when a DB transaction fails.
    def test_memo_create_endpoint_returns_500_when_db_transaction_fails(self):
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with self._make_client() as client:
                # 日本語: セッションにユーザーIDを設定
                # English: Set user_id in session
                await self._set_session(client, {"user_id": 7})
                # 日本語: メモ挿入時にエラーを発生させる
                # English: Raise error when inserting a memo
                with patch("blueprints.memo._insert_memo", side_effect=Error("tx failed")):
                    response = await self._post_with_csrf(
                        client,
                        "/memo/api",
                        json={
                            "ai_response": "ok",
                            "title": "",
                        },
                    )

            self.assertEqual(response.status_code, 500)
            payload = response.json()
            self.assertEqual(payload.get("status"), "fail")
            self.assertIn("error", payload)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
