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


def build_test_app():
    return build_session_test_app(
        auth_bp,
        memo_bp,
        secret_key="endpoint-test-secret",
        include_test_session_route=True,
    )


class EndpointRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = build_test_app()

    def _make_client(self, *, follow_redirects=True) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
            follow_redirects=follow_redirects,
        )

    async def _set_session(self, client: httpx.AsyncClient, values):
        response = await client.post("/_test/session", json=values)
        self.assertEqual(response.status_code, 200)

    async def _post_with_csrf(self, client: httpx.AsyncClient, path, *, json):
        csrf_token = "test-csrf-token"
        await self._set_session(client, {CSRF_SESSION_KEY: csrf_token})
        return await client.post(path, json=json, headers={CSRF_HEADER_NAME: csrf_token})

    def test_current_user_endpoint_when_logged_out(self):
        async def scenario():
            async with self._make_client() as client:
                response = await client.get("/api/current_user")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"logged_in": False})

        asyncio.run(scenario())

    def test_current_user_endpoint_when_logged_in(self):
        async def scenario():
            async with self._make_client() as client:
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

    def test_logout_endpoint_clears_session_and_redirects(self):
        async def scenario():
            async with self._make_client(follow_redirects=False) as client:
                csrf_token = "logout-csrf-token"
                await self._set_session(
                    client,
                    {
                        "user_id": 7,
                        "user_email": "user@example.com",
                        CSRF_SESSION_KEY: csrf_token,
                    },
                )
                response = await client.post(
                    "/logout",
                    headers={CSRF_HEADER_NAME: csrf_token},
                )
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.headers["location"].endswith("/login"))

                current_user = await client.get("/api/current_user")

            self.assertEqual(current_user.status_code, 200)
            self.assertEqual(current_user.json(), {"logged_in": False})

        asyncio.run(scenario())

    def test_memo_recent_endpoint_returns_serialized_memos(self):
        async def scenario():
            sample = {
                "id": 1,
                "title": "サンプル",
                "tags": "仕事",
                "created_at": datetime(2024, 1, 1, 9, 30),
                "input_content": "input",
                "ai_response": "response",
            }

            async with self._make_client() as client:
                await self._set_session(client, {"user_id": 7})
                with patch("blueprints.memo._fetch_recent_memos", return_value=[sample]):
                    response = await client.get("/memo/api/recent?limit=5")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["memos"][0]["id"], 1)
            self.assertEqual(payload["memos"][0]["created_at"], "2024-01-01 09:30")

        asyncio.run(scenario())

    def test_memo_recent_endpoint_requires_login(self):
        async def scenario():
            async with self._make_client() as client:
                response = await client.get("/memo/api/recent?limit=5")

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {"status": "fail", "error": "ログインが必要です"})

        asyncio.run(scenario())

    def test_memo_create_endpoint_validates_required_fields(self):
        async def scenario():
            async with self._make_client() as client:
                await self._set_session(client, {"user_id": 7})
                response = await self._post_with_csrf(
                    client,
                    "/memo/api",
                    json={"input_content": "hello", "ai_response": ""},
                )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["status"], "fail")

        asyncio.run(scenario())

    def test_memo_create_endpoint_success(self):
        async def scenario():
            async with self._make_client() as client:
                await self._set_session(client, {"user_id": 7})
                with patch("blueprints.memo._insert_memo", return_value=42):
                    response = await self._post_with_csrf(
                        client,
                        "/memo/api",
                        json={
                            "input_content": "hello",
                            "ai_response": "ok",
                            "title": "",
                            "tags": "",
                        },
                    )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["memo_id"], 42)

        asyncio.run(scenario())

    def test_memo_create_endpoint_requires_login(self):
        async def scenario():
            async with self._make_client() as client:
                response = await self._post_with_csrf(
                    client,
                    "/memo/api",
                    json={"input_content": "hello", "ai_response": "ok"},
                )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {"status": "fail", "error": "ログインが必要です"})

        asyncio.run(scenario())

    def test_memo_recent_endpoint_falls_back_to_empty_when_db_read_fails(self):
        async def scenario():
            async with self._make_client() as client:
                await self._set_session(client, {"user_id": 7})
                with patch("blueprints.memo.get_db_connection", side_effect=Error("db down")):
                    response = await client.get("/memo/api/recent?limit=5")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"memos": []})

        asyncio.run(scenario())

    def test_memo_recent_endpoint_db_failure_is_stable_under_concurrency(self):
        async def scenario():
            async with self._make_client() as client:
                await self._set_session(client, {"user_id": 7})
                with patch("blueprints.memo.get_db_connection", side_effect=Error("db down")):
                    responses = await asyncio.gather(
                        client.get("/memo/api/recent?limit=5"),
                        client.get("/memo/api/recent?limit=5"),
                        client.get("/memo/api/recent?limit=5"),
                        client.get("/memo/api/recent?limit=5"),
                    )

            for response in responses:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"memos": []})

        asyncio.run(scenario())

    def test_memo_create_endpoint_returns_500_when_db_transaction_fails(self):
        async def scenario():
            async with self._make_client() as client:
                await self._set_session(client, {"user_id": 7})
                with patch("blueprints.memo._insert_memo", side_effect=Error("tx failed")):
                    response = await self._post_with_csrf(
                        client,
                        "/memo/api",
                        json={
                            "input_content": "hello",
                            "ai_response": "ok",
                            "title": "",
                            "tags": "",
                        },
                    )

            self.assertEqual(response.status_code, 500)
            payload = response.json()
            self.assertEqual(payload.get("status"), "fail")
            self.assertIn("error", payload)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
