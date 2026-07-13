import json
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

from mcp.server.auth.provider import AuthorizationParams, AuthorizeError
from mcp.shared.auth import OAuthClientInformationFull

from services import mcp_oauth

SERVER_URL = "https://chat.example.test/mcp"


def _make_params(resource):
    return AuthorizationParams(
        state="state",
        scopes=[mcp_oauth.MCP_PROMPTS_WRITE_SCOPE],
        code_challenge="challenge",
        redirect_uri="https://client.example.test/callback",
        redirect_uri_provided_explicitly=True,
        resource=resource,
    )


class McpOAuthTestCase(unittest.TestCase):
    def test_consent_details_exposes_client_and_redirect_hosts(self):
        client = OAuthClientInformationFull(
            client_id="https://client.example.test/metadata.json",
            redirect_uris=["https://client.example.test/callback"],
            client_name="Example AI",
            token_endpoint_auth_method="none",
        )
        payload = {
            "client": mcp_oauth._serialize_client(client),
            "params": {
                "state": "state",
                "scopes": ["prompts:write"],
                "code_challenge": "challenge",
                "redirect_uri": "https://client.example.test/callback",
                "resource": "https://chat.example.test/mcp",
            },
        }
        with patch("services.mcp_oauth.get_session_secret_key", return_value="test-secret"):
            token = mcp_oauth._consent_serializer().dumps(payload)
            details = mcp_oauth.consent_details(token)

        self.assertEqual(details["client_name"], "Example AI")
        self.assertEqual(details["client_host"], "client.example.test")
        self.assertFalse(details["localhost_warning"])

    def test_consent_details_uses_redirect_host_for_an_opaque_client_id(self):
        client = OAuthClientInformationFull(
            client_id="claude-personal-client",
            redirect_uris=[mcp_oauth.DEFAULT_MCP_OAUTH_REDIRECT_URI],
            client_name="Claude",
            token_endpoint_auth_method="client_secret_post",
        )
        payload = {
            "client": mcp_oauth._serialize_client(client),
            "params": {
                "state": "state",
                "scopes": ["prompts:write"],
                "code_challenge": "challenge",
                "redirect_uri": mcp_oauth.DEFAULT_MCP_OAUTH_REDIRECT_URI,
                "resource": "https://chat.example.test/mcp",
            },
        }
        with patch("services.mcp_oauth.get_session_secret_key", return_value="test-secret"):
            token = mcp_oauth._consent_serializer().dumps(payload)
            details = mcp_oauth.consent_details(token)

        self.assertEqual(details["client_host"], "claude.ai")

    def test_refresh_keeps_same_token_alive_without_rotation(self):
        """リフレッシュしても同じリフレッシュトークンを返し、失効させないことを保証する。"""
        refresh = mcp_oauth.StoredRefreshToken(
            token="refresh-token-value",
            client_id="mcp-personal-client",
            scopes=[mcp_oauth.MCP_PROMPTS_WRITE_SCOPE],
            expires_at=9999999999,
            subject="7",
            grant_id=uuid4(),
            resource=SERVER_URL,
        )
        cursor = MagicMock()
        cursor.rowcount = 1

        @contextmanager
        def fake_connection():
            conn = MagicMock()
            conn.cursor.return_value = cursor
            yield conn

        with patch("services.mcp_oauth.get_db_connection", fake_connection):
            token = mcp_oauth._refresh_access_token(refresh, [mcp_oauth.MCP_PROMPTS_WRITE_SCOPE])

        # 同じリフレッシュトークンを返す（回転させない）。
        self.assertEqual(token.refresh_token, "refresh-token-value")
        # 新しいアクセストークンが発行される。
        self.assertTrue(token.access_token)
        self.assertNotEqual(token.access_token, "refresh-token-value")
        self.assertEqual(token.expires_in, mcp_oauth.ACCESS_TOKEN_TTL_SECONDS)
        # 既存のリフレッシュトークンを失効させる UPDATE を発行していないこと。
        executed_sql = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
        self.assertNotIn("revoked_at = NOW()", executed_sql)

    def test_revoke_user_client_severs_connections(self):
        """認証情報を削除したら、その grant とトークンも失効させることを保証する。"""
        cursor = MagicMock()
        cursor.rowcount = 1

        @contextmanager
        def fake_connection():
            conn = MagicMock()
            conn.cursor.return_value = cursor
            yield conn

        with patch("services.mcp_oauth.get_db_connection", fake_connection):
            result = mcp_oauth.revoke_user_client(user_id=7, client_id="mcp-personal-client")

        self.assertTrue(result)
        executed_sql = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
        # クライアント・トークン・grant の3つを失効させている。
        self.assertIn("UPDATE mcp_oauth_user_clients", executed_sql)
        self.assertIn("UPDATE mcp_oauth_tokens", executed_sql)
        self.assertIn("UPDATE mcp_oauth_grants", executed_sql)

    def test_revoke_user_client_missing_credential_leaves_connections(self):
        """存在しない認証情報の削除では grant/トークンを失効させず False を返す。"""
        cursor = MagicMock()
        cursor.rowcount = 0

        @contextmanager
        def fake_connection():
            conn = MagicMock()
            conn.cursor.return_value = cursor
            yield conn

        with patch("services.mcp_oauth.get_db_connection", fake_connection):
            result = mcp_oauth.revoke_user_client(user_id=7, client_id="mcp-missing")

        self.assertFalse(result)
        executed_sql = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
        self.assertNotIn("UPDATE mcp_oauth_grants", executed_sql)
        self.assertNotIn("UPDATE mcp_oauth_tokens", executed_sql)

    def test_redirect_validation_rejects_non_loopback_http(self):
        client = OAuthClientInformationFull(
            client_id="client",
            redirect_uris=["http://example.test/callback"],
            token_endpoint_auth_method="none",
        )
        with self.assertRaises(mcp_oauth.RegistrationError):
            mcp_oauth._validate_redirect_uris(client)

    def test_issue_user_client_stores_user_selected_redirect_uri(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"active": 0}

        @contextmanager
        def fake_connection():
            conn = MagicMock()
            conn.cursor.return_value = cursor
            yield conn

        fernet = MagicMock()
        fernet.encrypt.return_value = b"encrypted-secret"
        redirect_uri = "https://client.example.test/oauth/callback"
        with (
            patch("services.mcp_oauth._user_is_verified", return_value=True),
            patch("services.mcp_oauth.get_db_connection", fake_connection),
            patch("services.mcp_oauth._fernet", return_value=fernet),
            patch("services.mcp_oauth.get_mcp_server_url", return_value=SERVER_URL),
        ):
            credentials = mcp_oauth.issue_user_client(7, "Example AI", redirect_uri)

        stored_client = json.loads(cursor.execute.call_args_list[2].args[1][1])
        self.assertEqual(credentials["redirect_uri"], redirect_uri)
        self.assertEqual(stored_client["redirect_uris"], [redirect_uri])
        self.assertIsNone(stored_client.get("client_uri"))

    def test_clean_redirect_uri_rejects_non_loopback_http(self):
        with self.assertRaises(mcp_oauth.InvalidRedirectUriError):
            mcp_oauth._clean_redirect_uri("http://client.example.test/callback")

    def test_resource_matches_server_accepts_missing_or_canonical(self):
        with patch("services.mcp_oauth.get_mcp_server_url", return_value=SERVER_URL):
            # ChatGPT omits the resource indicator entirely.
            self.assertTrue(mcp_oauth._resource_matches_server(None))
            self.assertTrue(mcp_oauth._resource_matches_server(""))
            self.assertTrue(mcp_oauth._resource_matches_server(SERVER_URL))
            # Trailing slash differences must not break the match.
            self.assertTrue(mcp_oauth._resource_matches_server(SERVER_URL + "/"))
            # A different resource is rejected.
            self.assertFalse(mcp_oauth._resource_matches_server("https://evil.example.test/mcp"))

    def test_authorize_allows_missing_resource_and_stores_canonical(self):
        client = OAuthClientInformationFull(
            client_id="https://client.example.test/metadata.json",
            redirect_uris=["https://client.example.test/callback"],
            token_endpoint_auth_method="none",
        )
        provider = mcp_oauth.ChatCoreOAuthProvider()
        captured = {}

        def fake_dumps(payload):
            captured["payload"] = payload
            return "signed-token"

        with (
            patch("services.mcp_oauth.get_mcp_server_url", return_value=SERVER_URL),
            patch("services.mcp_oauth.get_mcp_public_base_url", return_value="https://chat.example.test"),
            patch("services.mcp_oauth._consent_serializer") as serializer,
        ):
            serializer.return_value.dumps.side_effect = fake_dumps
            import asyncio

            redirect = asyncio.run(provider.authorize(client, _make_params(None)))

        self.assertEqual(redirect, "https://chat.example.test/oauth/authorize?request=signed-token")
        # Even without an incoming resource, the stored grant is pinned to this server.
        self.assertEqual(captured["payload"]["params"]["resource"], SERVER_URL)

    def test_authorize_rejects_foreign_resource(self):
        client = OAuthClientInformationFull(
            client_id="https://client.example.test/metadata.json",
            redirect_uris=["https://client.example.test/callback"],
            token_endpoint_auth_method="none",
        )
        provider = mcp_oauth.ChatCoreOAuthProvider()
        with patch("services.mcp_oauth.get_mcp_server_url", return_value=SERVER_URL):
            import asyncio

            with self.assertRaises(AuthorizeError) as ctx:
                asyncio.run(provider.authorize(client, _make_params("https://evil.example.test/mcp")))
        self.assertEqual(ctx.exception.error, "invalid_request")

    def test_complete_consent_rejects_a_personal_client_owned_by_another_user(self):
        request_data = {
            "client": {"client_id": "claude-personal-client"},
            "params": {"redirect_uri": "https://claude.ai/api/mcp/auth_callback", "state": "state"},
        }
        with (
            patch("services.mcp_oauth.read_consent_request", return_value=request_data),
            patch("services.mcp_oauth._user_is_verified", return_value=True),
            patch("services.mcp_oauth._user_client_is_authorized_for_user", return_value=False),
            patch("services.mcp_oauth._create_authorization_code") as create_code,
        ):
            redirect = mcp_oauth.complete_consent("signed-request", user_id=7, approved=True)

        self.assertIsNone(redirect)
        create_code.assert_not_called()

    def test_complete_consent_allows_a_personal_client_owned_by_the_user(self):
        request_data = {
            "client": {"client_id": "claude-personal-client"},
            "params": {"redirect_uri": "https://claude.ai/api/mcp/auth_callback", "state": "state"},
        }
        with (
            patch("services.mcp_oauth.read_consent_request", return_value=request_data),
            patch("services.mcp_oauth._user_is_verified", return_value=True),
            patch("services.mcp_oauth._user_client_is_authorized_for_user", return_value=True),
            patch("services.mcp_oauth._create_authorization_code", return_value="authorization-code"),
        ):
            redirect = mcp_oauth.complete_consent("signed-request", user_id=7, approved=True)

        self.assertEqual(
            redirect,
            "https://claude.ai/api/mcp/auth_callback?code=authorization-code&state=state",
        )
