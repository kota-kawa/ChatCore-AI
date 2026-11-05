"""コンテキストボールトの API を、ルーターとセッション・CSRF ミドルウェアを通して検証する統合テスト。
サービス層（create_fact / update_fact）だけをモックする。

Integration tests for the context-vault API through the router and the session and CSRF middleware.
Only the service layer (create_fact / update_fact) is mocked.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from blueprints.context_vault import context_vault_bp
from services.api_errors import ApiServiceError
from services.csrf import CSRF_HEADER_NAME, CSRF_SESSION_KEY
from services.response_models import ContextFactResponse
from tests.helpers.app_helpers import build_session_test_app


# 日本語: ContextFactResponse のテスト用既定値を作る。overrides で個別のフィールドを上書きできる。
# English: Build a default ContextFactResponse for tests; overrides replaces individual fields.
def _fact_response(**overrides):
    payload = {
        "id": 3,
        "fact_type": "preference",
        "title": "Editor",
        "content": "Uses vim",
        "status": "active",
        "revision": 1,
        "source_kind": "manual",
        "importance": 50,
        "created_at": None,
        "updated_at": None,
    }
    payload.update(overrides)
    return ContextFactResponse(**payload)


# 日本語: 未ログインは 401、CSRF なしの書き込みは 403、サービスが 409 を返す場合の応答形式をルーター経由で確かめる。
#         （pydantic のレスポンスモデルを import しているため、docstring ではなくコメントで書く）
# English: Checks, through the router, 401 when logged out, 403 for writes without CSRF,
#          and the response shape when the service returns 409.
#          (Written as a comment, not a docstring, because this file imports pydantic response models.)
class ContextVaultEndpointIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = build_session_test_app(
            context_vault_bp,
            secret_key="context-vault-endpoint-test-secret",
            include_test_session_route=True,
        )

    # 日本語: ネットワークを使わず、ASGI アプリへ直接つなぐ非同期 HTTP クライアントを作る。
    # English: Create an async HTTP client wired straight to the ASGI app, without any network.
    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    async def _set_session(self, client: httpx.AsyncClient, values):
        response = await client.post("/_test/session", json=values)
        self.assertEqual(response.status_code, 200)

    # 日本語: ログイン済みかつ CSRF トークン入りのセッションを作り、そのトークンを返す。
    # English: Seed a logged-in session that holds a CSRF token, and return that token.
    async def _authenticate_with_csrf(self, client: httpx.AsyncClient) -> str:
        token = "context-vault-csrf-token"
        await self._set_session(
            client,
            {
                "user_id": 7,
                CSRF_SESSION_KEY: token,
            },
        )
        return token

    def test_list_requires_authenticated_session_through_router(self):
        async def scenario():
            async with self._make_client() as client:
                response = await client.get("/api/context-facts")

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"], "ログインが必要です")

        asyncio.run(scenario())

    def test_create_and_update_reject_missing_csrf_through_router(self):
        async def scenario():
            async with self._make_client() as client:
                await self._set_session(client, {"user_id": 7})
                create_response = await client.post(
                    "/api/context-facts",
                    json={
                        "fact_type": "preference",
                        "title": "Editor",
                        "content": "Uses vim",
                    },
                )
                update_response = await client.put(
                    "/api/context-facts/3",
                    json={"revision": 1, "status": "deprecated"},
                )

            self.assertEqual(create_response.status_code, 403)
            self.assertIn("CSRF", create_response.json()["detail"])
            self.assertEqual(update_response.status_code, 403)
            self.assertIn("CSRF", update_response.json()["detail"])

        asyncio.run(scenario())

    def test_create_returns_wrapped_fact_through_router(self):
        async def scenario():
            async with self._make_client() as client:
                token = await self._authenticate_with_csrf(client)
                with patch(
                    "blueprints.context_vault.routes.create_fact",
                    new=AsyncMock(return_value=_fact_response(importance=75)),
                ) as create:
                    response = await client.post(
                        "/api/context-facts",
                        json={
                            "fact_type": "preference",
                            "title": "Editor",
                            "content": "Uses vim",
                            "importance": 75,
                        },
                        headers={CSRF_HEADER_NAME: token},
                    )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "success")
            self.assertEqual(response.json()["fact"]["id"], 3)
            create.assert_awaited_once()
            self.assertEqual(create.call_args.kwargs["importance"], 75)

        asyncio.run(scenario())

    def test_create_limit_and_update_revision_conflict_return_409_through_router(self):
        async def scenario():
            async with self._make_client() as client:
                token = await self._authenticate_with_csrf(client)
                headers = {CSRF_HEADER_NAME: token}
                conflict = ApiServiceError("競合しました。", 409, status="fail")
                with patch(
                    "blueprints.context_vault.routes.create_fact",
                    new=AsyncMock(
                        side_effect=ApiServiceError(
                            "有効なコンテキストは200件までです。",
                            409,
                            status="fail",
                        )
                    ),
                ):
                    create_response = await client.post(
                        "/api/context-facts",
                        json={
                            "fact_type": "preference",
                            "title": "Editor",
                            "content": "Uses vim",
                        },
                        headers=headers,
                    )
                with patch(
                    "blueprints.context_vault.routes.update_fact",
                    new=AsyncMock(side_effect=conflict),
                ):
                    update_response = await client.put(
                        "/api/context-facts/3",
                        json={"revision": 1, "status": "deprecated"},
                        headers=headers,
                    )

            self.assertEqual(create_response.status_code, 409)
            self.assertEqual(update_response.status_code, 409)
            self.assertEqual(update_response.json()["error"], "競合しました。")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
