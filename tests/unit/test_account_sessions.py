import asyncio
import unittest
from http.cookies import SimpleCookie
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Request

from blueprints.auth import auth_bp
from services.auth_session import establish_authenticated_session
from services.csrf import CSRF_HEADER_NAME, CSRF_SESSION_KEY
from services.session_middleware import PermanentSessionMiddleware
from services.session_scope import MAX_PARKED_SESSIONS
from tests.unit.test_session_middleware import DummyRedis

USERS = {
    user_id: {
        "id": user_id,
        "email": f"user{user_id}@example.com",
        "username": f"User {user_id}",
        "avatar_url": f"/static/uploads/{user_id}.png",
    }
    for user_id in range(1, 8)
}


async def fake_get_user_by_id(user_id):
    return USERS.get(user_id)


def build_app():
    app = FastAPI()
    app.add_middleware(PermanentSessionMiddleware, secret_key="account-sessions-test-secret", max_age=3600)
    app.include_router(auth_bp)

    # 認証方式ごとの検証は別のテストが担うので、成功後の共通処理だけを通す
    # Each sign-in method is covered elsewhere; this only runs the shared post-success step.
    @app.post("/_test/login/{user_id}")
    async def test_login(request: Request, user_id: int):
        establish_authenticated_session(request, user_id, USERS[user_id]["email"])
        return {"status": "ok"}

    @app.get("/_test/session")
    async def test_session(request: Request):
        return {
            "user_id": request.session.get("user_id"),
            "is_admin": request.session.get("is_admin"),
            "csrf_token": request.session[CSRF_SESSION_KEY],
        }

    @app.post("/_test/admin")
    async def test_admin(request: Request):
        request.session["is_admin"] = True
        return {"status": "ok"}

    # 応答を返す前に、別のリクエストを割り込ませるための遅いルート
    # A slow route that lets another request run before it responds
    @app.get("/_test/slow")
    async def test_slow(request: Request):
        await request.app.state.slow_route_gate()
        return {"user_id": request.session.get("user_id")}

    return app


# 同じブラウザで複数アカウントのログイン状態を保持し、切り替え・ログアウトできることを検証する。
# Verify that one browser can hold several signed-in accounts, switch between them and sign out of one.
class AccountSessionsTestCase(unittest.TestCase):
    def run_scenario(self, scenario, redis_client=None):
        redis_client = redis_client or DummyRedis()

        async def runner():
            transport = httpx.ASGITransport(app=build_app())
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                await scenario(client, redis_client)

        with (
            patch("services.session_middleware.get_redis_client", return_value=redis_client),
            patch("services.account_sessions.get_redis_client", return_value=redis_client),
            patch("blueprints.auth.get_user_by_id", side_effect=fake_get_user_by_id),
            patch("blueprints.auth.frontend_url", side_effect=lambda path="": f"http://frontend{path}"),
            patch("blueprints.auth.frontend_login_url", return_value="http://frontend/login"),
        ):
            asyncio.run(runner())

    @staticmethod
    async def post(client, path, **kwargs):
        csrf_token = (await client.get("/_test/session")).json()["csrf_token"]
        return await client.post(path, headers={CSRF_HEADER_NAME: csrf_token}, **kwargs)

    @staticmethod
    async def current_user_id(client):
        return (await client.get("/_test/session")).json()["user_id"]

    @staticmethod
    async def listed_accounts(client):
        response = await client.get("/api/auth/accounts")
        return [(account["user_id"], account["current"]) for account in response.json()["accounts"]]

    def test_signing_in_to_another_account_keeps_the_first_one_switchable(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            first_session_cookie = client.cookies["session"]
            await client.post("/_test/login/2")

            self.assertNotEqual(client.cookies["session"], first_session_cookie)
            self.assertEqual(len(redis_client.store), 2)
            self.assertEqual(await self.listed_accounts(client), [(2, True), (1, False)])

            response = await client.get("/api/auth/accounts")
            self.assertEqual(
                response.json()["accounts"][1],
                {
                    "user_id": 1,
                    "username": "User 1",
                    "email": "user1@example.com",
                    "avatar_url": "/static/uploads/1.png",
                    "current": False,
                },
            )

        self.run_scenario(scenario)

    def test_switch_swaps_the_active_and_parked_sessions(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            first_session_cookie = client.cookies["session"]
            await client.post("/_test/login/2")

            response = await self.post(client, "/api/auth/accounts/switch", json={"user_id": 1})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.cookies["session"], first_session_cookie)
            self.assertEqual(await self.current_user_id(client), 1)
            self.assertEqual(await self.listed_accounts(client), [(1, True), (2, False)])
            self.assertEqual(len(redis_client.store), 2)

        self.run_scenario(scenario)

    def test_switch_requires_csrf_token(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            await client.post("/_test/login/2")

            response = await client.post("/api/auth/accounts/switch", json={"user_id": 1})

            self.assertEqual(response.status_code, 403)
            self.assertEqual(await self.current_user_id(client), 2)

        self.run_scenario(scenario)

    def test_switch_rejects_accounts_without_a_parked_session(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")

            for payload in ({"user_id": 2}, {"user_id": "1"}, {"user_id": True}, {}):
                with self.subTest(payload=payload):
                    response = await self.post(client, "/api/auth/accounts/switch", json=payload)
                    self.assertIn(response.status_code, (400, 404))
            self.assertEqual(await self.current_user_id(client), 1)

        self.run_scenario(scenario)

    def test_account_endpoints_require_login(self):
        async def scenario(client, redis_client):
            self.assertEqual((await client.get("/api/auth/accounts")).status_code, 401)
            response = await self.post(client, "/api/auth/accounts/switch", json={"user_id": 1})
            self.assertEqual(response.status_code, 401)

        self.run_scenario(scenario)

    def test_logout_signs_out_only_the_active_account(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            await client.post("/_test/login/2")

            response = await self.post(client, "/logout")

            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["location"], "http://frontend/")
            self.assertEqual(await self.current_user_id(client), 1)
            self.assertEqual(await self.listed_accounts(client), [(1, True)])
            # ログアウトしたアカウントのセッションは Redis からも消える
            # The signed-out account's session is gone from Redis as well
            self.assertEqual(len(redis_client.store), 1)

            response = await self.post(client, "/logout")

            self.assertEqual(response.headers["location"], "http://frontend/login")
            self.assertEqual(redis_client.store, {})
            self.assertIsNone(await self.current_user_id(client))

        self.run_scenario(scenario)

    def test_signed_out_account_cannot_be_switched_to(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            await client.post("/_test/login/2")
            await self.post(client, "/logout")
            await client.post("/_test/login/3")

            response = await self.post(client, "/api/auth/accounts/switch", json={"user_id": 2})

            self.assertEqual(response.status_code, 404)
            self.assertEqual(await self.current_user_id(client), 3)

        self.run_scenario(scenario)

    def test_signing_in_again_to_a_parked_account_drops_its_old_session(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            await client.post("/_test/login/2")
            await client.post("/_test/login/1")

            self.assertEqual(await self.listed_accounts(client), [(1, True), (2, False)])
            self.assertEqual(len(redis_client.store), 2)

        self.run_scenario(scenario)

    def test_signing_in_to_the_same_account_rotates_instead_of_parking(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            await client.post("/_test/login/1")

            self.assertEqual(await self.listed_accounts(client), [(1, True)])
            self.assertEqual(len(redis_client.store), 1)

        self.run_scenario(scenario)

    def test_added_account_does_not_inherit_the_admin_flag(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            await client.post("/_test/admin")
            await client.post("/_test/login/2")

            self.assertIsNone((await client.get("/_test/session")).json()["is_admin"])

            await self.post(client, "/api/auth/accounts/switch", json={"user_id": 1})

            self.assertTrue((await client.get("/_test/session")).json()["is_admin"])

        self.run_scenario(scenario)

    def test_request_started_before_a_switch_does_not_revert_the_active_account(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            await client.post("/_test/login/2")
            app = client._transport.app

            # アカウント 2 のリクエストが処理中の間に、アカウント 1 へ切り替える
            # Switch to account 1 while a request of account 2 is still in flight
            async def switch_while_waiting():
                response = await self.post(client, "/api/auth/accounts/switch", json={"user_id": 1})
                self.assertEqual(response.status_code, 200)

            app.state.slow_route_gate = switch_while_waiting
            slow_response = await client.get("/_test/slow")

            self.assertEqual(slow_response.json()["user_id"], 2)
            self.assertNotIn("set-cookie", slow_response.headers)
            self.assertEqual(await self.current_user_id(client), 1)

            # 切り替え前の Cookie を持ったまま後から届いたリクエストも、Cookie を戻さない
            # A request that arrives late with the pre-switch cookie does not revert it either
            async def no_wait():
                return None

            app.state.slow_route_gate = no_wait
            parked_cookie = slow_response.request.headers["cookie"]
            late_response = await client.get("/_test/slow", headers={"cookie": parked_cookie})
            self.assertNotIn("set-cookie", late_response.headers)

        self.run_scenario(scenario)

    def test_signing_in_again_does_not_push_out_another_account_at_the_limit(self):
        async def scenario(client, redis_client):
            for user_id in range(1, MAX_PARKED_SESSIONS + 2):
                await client.post(f"/_test/login/{user_id}")
            await client.post("/_test/login/3")

            accounts = await self.listed_accounts(client)

            self.assertEqual(sorted(user_id for user_id, _ in accounts), list(range(1, MAX_PARKED_SESSIONS + 2)))
            self.assertEqual(len(redis_client.store), MAX_PARKED_SESSIONS + 1)

        self.run_scenario(scenario)

    def test_account_deleted_while_parked_is_not_activated(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            await client.post("/_test/login/2")

            with patch("blueprints.auth.get_user_by_id", return_value=None):
                response = await self.post(client, "/api/auth/accounts/switch", json={"user_id": 1})
                self.assertEqual(response.status_code, 404)
                response = await self.post(client, "/logout")

            self.assertEqual(response.headers["location"], "http://frontend/login")

        self.run_scenario(scenario)

    def test_oldest_parked_session_is_deleted_beyond_the_limit(self):
        async def scenario(client, redis_client):
            for user_id in range(1, MAX_PARKED_SESSIONS + 3):
                await client.post(f"/_test/login/{user_id}")

            accounts = await self.listed_accounts(client)

            self.assertEqual(len(accounts), MAX_PARKED_SESSIONS + 1)
            self.assertNotIn((1, False), accounts)
            self.assertEqual(len(redis_client.store), MAX_PARKED_SESSIONS + 1)

        self.run_scenario(scenario)

    def test_expired_parked_session_is_dropped_from_the_list(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            parked_key = next(iter(redis_client.store))
            await client.post("/_test/login/2")
            del redis_client.store[parked_key]

            self.assertEqual(await self.listed_accounts(client), [(2, True)])
            response = await self.post(client, "/logout")
            self.assertEqual(response.headers["location"], "http://frontend/login")

        self.run_scenario(scenario)

    def test_tampered_parked_cookie_is_ignored(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            victim_session_id = next(iter(redis_client.store)).removeprefix("session:")
            client.cookies.clear()
            await client.post("/_test/login/2")
            client.cookies.set("session_accounts", f'["{victim_session_id}"]')

            self.assertEqual(await self.listed_accounts(client), [(2, True)])
            response = await self.post(client, "/api/auth/accounts/switch", json={"user_id": 1})
            self.assertEqual(response.status_code, 404)

        self.run_scenario(scenario)

    def test_parked_cookie_is_http_only_and_holds_no_account_data(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            response = await client.post("/_test/login/2")

            cookie = SimpleCookie()
            for header in response.headers.get_list("set-cookie"):
                cookie.load(header)
            self.assertTrue(cookie["session_accounts"]["httponly"])
            self.assertNotIn("user1@example.com", cookie["session_accounts"].value)

        self.run_scenario(scenario)

    def test_redis_outage_does_not_discard_parked_accounts(self):
        async def scenario(client, redis_client):
            await client.post("/_test/login/1")
            await client.post("/_test/login/2")
            parked_cookie = client.cookies["session_accounts"]

            with patch("services.account_sessions.get_redis_client", return_value=None):
                response = await self.post(client, "/api/auth/accounts/switch", json={"user_id": 1})
                accounts = await self.listed_accounts(client)

            self.assertEqual(response.status_code, 503)
            self.assertEqual(accounts, [(2, True)])
            self.assertEqual(client.cookies["session_accounts"], parked_cookie)
            self.assertEqual(await self.listed_accounts(client), [(2, True), (1, False)])

        self.run_scenario(scenario)


if __name__ == "__main__":
    unittest.main()
