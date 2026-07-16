import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from blueprints.auth import (
    auth_bp,
    api_passkey_authenticate_options,
    api_passkey_authenticate_verify,
    api_send_email_code,
    api_send_login_code,
    api_verify_login_code,
)
from services.csrf import CSRF_HEADER_NAME, CSRF_SESSION_KEY
from tests.helpers.app_helpers import build_session_test_app


class AuthDependencyInjectionTestCase(unittest.TestCase):
    def assert_request_is_not_a_query_parameter(self, endpoint):
        app = FastAPI()
        app.post("/test")(endpoint)

        parameters = app.openapi()["paths"]["/test"]["post"].get("parameters", [])

        self.assertNotIn(
            ("request", "query"),
            {(parameter["name"], parameter["in"]) for parameter in parameters},
        )

    def test_passkey_authentication_routes_inject_request(self):
        for endpoint in (
            api_passkey_authenticate_options,
            api_passkey_authenticate_verify,
        ):
            with self.subTest(endpoint=endpoint.__name__):
                self.assert_request_is_not_a_query_parameter(endpoint)

    def test_email_authentication_routes_inject_request(self):
        for endpoint in (
            api_send_email_code,
            api_send_login_code,
            api_verify_login_code,
        ):
            with self.subTest(endpoint=endpoint.__name__):
                self.assert_request_is_not_a_query_parameter(endpoint)

    def test_passkey_authentication_options_request_reaches_handler(self):
        async def scenario():
            app = build_session_test_app(
                auth_bp,
                secret_key="passkey-dependency-test-secret",
                include_test_session_route=True,
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                csrf_token = "passkey-csrf-token"
                session_response = await client.post(
                    "/_test/session",
                    json={CSRF_SESSION_KEY: csrf_token},
                )
                self.assertEqual(session_response.status_code, 200)

                options = SimpleNamespace(challenge=b"passkey-challenge")
                with patch(
                    "blueprints.auth.consume_passkey_auth_options_limit",
                    return_value=(True, None),
                ):
                    with patch(
                        "blueprints.auth.generate_authentication_options",
                        return_value=options,
                    ):
                        with patch(
                            "blueprints.auth.options_to_json",
                            return_value='{"challenge":"passkey-challenge"}',
                        ):
                            with patch(
                                "blueprints.auth.bytes_to_base64url",
                                return_value="passkey-challenge",
                            ):
                                response = await client.post(
                                    "/api/passkeys/authenticate/options",
                                    headers={CSRF_HEADER_NAME: csrf_token},
                                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["challenge"], "passkey-challenge")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
