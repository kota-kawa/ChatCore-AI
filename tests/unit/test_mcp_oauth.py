import asyncio
import json
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from mcp.server.auth.provider import AuthorizationParams, AuthorizeError
from mcp.shared.auth import InvalidRedirectUriError as McpInvalidRedirectUriError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from services import mcp_oauth

SERVER_URL = "https://chat.example.test/mcp"


def _make_params(resource, scopes=None):
    return AuthorizationParams(
        state="state",
        scopes=[mcp_oauth.MCP_PROMPTS_WRITE_SCOPE] if scopes is None else scopes,
        code_challenge="challenge",
        redirect_uri="https://client.example.test/callback",
        redirect_uri_provided_explicitly=True,
        resource=resource,
    )


class McpOAuthTestCase(unittest.TestCase):
    def test_cimd_loads_a_public_client_from_its_metadata_url(self):
        client_id = "https://client.example.test/oauth/client.json"
        response = MagicMock()
        response.status_code = 200
        response.headers = {"content-type": "application/json"}
        response.iter_content.return_value = [
            json.dumps(
                {
                    "client_id": client_id,
                    "client_name": "URL-only MCP client",
                    "redirect_uris": ["https://client.example.test/oauth/callback"],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "none",
                }
            ).encode("utf-8")
        ]

        @contextmanager
        def fake_dns_pin(_mapping):
            yield

        mcp_oauth._cimd_cache.clear()
        try:
            with (
                patch("services.mcp_oauth._resolve_safe_ip", return_value="203.0.113.10"),
                patch("services.mcp_oauth._pin_dns", fake_dns_pin),
                patch("services.mcp_oauth.requests.get", return_value=response),
            ):
                client = mcp_oauth._cimd_client(client_id)
        finally:
            mcp_oauth._cimd_cache.clear()

        self.assertIsNotNone(client)
        self.assertEqual(str(client.client_id), client_id)
        self.assertEqual(client.token_endpoint_auth_method, "none")
        self.assertEqual(client.scope, " ".join(mcp_oauth.MCP_ALLOWED_SCOPES))
        self.assertEqual(
            client.validate_scope(
                f"{mcp_oauth.MCP_PROMPTS_READ_SCOPE} {mcp_oauth.MCP_MEMOS_READ_SCOPE}"
            ),
            [mcp_oauth.MCP_PROMPTS_READ_SCOPE, mcp_oauth.MCP_MEMOS_READ_SCOPE],
        )
        response.close.assert_called_once()

    def test_cimd_client_accepts_claude_code_ephemeral_loopback_port(self):
        client = mcp_oauth.CimdOAuthClientInformation(
            client_id="https://claude.ai/oauth/client-metadata",
            redirect_uris=[
                "http://localhost/callback",
                "http://127.0.0.1/callback",
            ],
            token_endpoint_auth_method="none",
        )

        localhost = AnyUrl("http://localhost:3118/callback")
        loopback_ip = AnyUrl("http://127.0.0.1:49231/callback")
        self.assertEqual(client.validate_redirect_uri(localhost), localhost)
        self.assertEqual(client.validate_redirect_uri(loopback_ip), loopback_ip)

        with self.assertRaises(McpInvalidRedirectUriError):
            client.validate_redirect_uri(AnyUrl("http://localhost:3118/different"))

    def test_cimd_cache_is_bounded(self):
        mcp_oauth._cimd_cache.clear()
        try:
            with patch("services.mcp_oauth.get_mcp_cimd_cache_entries", return_value=2):
                mcp_oauth._write_cimd_cache("first", None, 60)
                mcp_oauth._write_cimd_cache("second", None, 60)
                mcp_oauth._write_cimd_cache("third", None, 60)

            self.assertNotIn("first", mcp_oauth._cimd_cache)
            self.assertEqual(set(mcp_oauth._cimd_cache), {"second", "third"})
        finally:
            mcp_oauth._cimd_cache.clear()

    def test_cimd_fetch_is_rejected_when_concurrency_limit_is_full(self):
        slots = MagicMock()
        slots.acquire.return_value = False
        with patch("services.mcp_oauth._get_cimd_executor", return_value=(MagicMock(), slots)):
            result = asyncio.run(mcp_oauth._load_cimd_client("https://client.example/metadata.json"))

        self.assertIsNone(result)
        slots.release.assert_not_called()

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
        self.assertEqual(details["scopes"], [mcp_oauth.MCP_PROMPTS_WRITE_SCOPE])
        self.assertEqual(
            details["scope_labels"],
            {mcp_oauth.MCP_PROMPTS_WRITE_SCOPE: "公開プロンプトを投稿する"},
        )
        self.assertFalse(details["localhost_warning"])

    def test_consent_details_exposes_each_requested_scope_and_label(self):
        client = OAuthClientInformationFull(
            client_id="https://client.example.test/metadata.json",
            redirect_uris=["https://client.example.test/callback"],
            client_name="Example AI",
            token_endpoint_auth_method="none",
        )
        requested_scopes = [
            mcp_oauth.MCP_PROMPTS_READ_SCOPE,
            mcp_oauth.MCP_MEMOS_READ_SCOPE,
            mcp_oauth.MCP_MEMOS_WRITE_SCOPE,
        ]
        payload = {
            "client": mcp_oauth._serialize_client(client),
            "params": {
                "state": "state",
                "scopes": requested_scopes,
                "code_challenge": "challenge",
                "redirect_uri": "https://client.example.test/callback",
                "resource": SERVER_URL,
            },
        }
        with patch("services.mcp_oauth.get_session_secret_key", return_value="test-secret"):
            token = mcp_oauth._consent_serializer().dumps(payload)
            details = mcp_oauth.consent_details(token)

        self.assertEqual(details["scope"], " ".join(requested_scopes))
        self.assertEqual(details["scopes"], requested_scopes)
        self.assertEqual(
            details["scope_labels"][mcp_oauth.MCP_MEMOS_READ_SCOPE],
            "保存したメモを検索・閲覧する",
        )

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

    def _refresh_token(self, grant_id=None):
        return mcp_oauth.StoredRefreshToken(
            token="refresh-token-value",
            client_id="mcp-personal-client",
            scopes=[mcp_oauth.MCP_PROMPTS_WRITE_SCOPE],
            expires_at=9999999999,
            subject="7",
            grant_id=grant_id or uuid4(),
            resource=SERVER_URL,
        )

    def test_refresh_rotates_the_refresh_token(self):
        """リフレッシュすると新しいリフレッシュトークンを発行し、提示分は即失効させず猶予マーカーを立てる。"""
        refresh = self._refresh_token()
        cursor = MagicMock()
        cursor.rowcount = 1

        @contextmanager
        def fake_connection():
            conn = MagicMock()
            conn.cursor.return_value = cursor
            yield conn

        with patch("services.mcp_oauth.get_db_connection", fake_connection):
            token = mcp_oauth._refresh_access_token(refresh, [mcp_oauth.MCP_PROMPTS_WRITE_SCOPE])

        # 回転している：新しいリフレッシュトークンを返す。
        self.assertTrue(token.refresh_token)
        self.assertNotEqual(token.refresh_token, "refresh-token-value")
        # 新しいアクセストークンも発行される（リフレッシュトークンとは別物）。
        self.assertTrue(token.access_token)
        self.assertNotEqual(token.access_token, token.refresh_token)
        self.assertEqual(token.expires_in, mcp_oauth.ACCESS_TOKEN_TTL_SECONDS)
        executed_sql = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
        # 提示されたトークンは replaced_at を立てるだけで即 revoke しない（猶予期間で接続を維持）。
        self.assertIn("replaced_at = COALESCE(replaced_at", executed_sql)
        self.assertNotIn("revoked_at = NOW()", executed_sql)

    def test_refresh_rejects_scope_escalation_before_writing_tokens(self):
        refresh = self._refresh_token()
        with (
            patch("services.mcp_oauth.get_db_connection") as get_connection,
            self.assertRaises(mcp_oauth.TokenError) as context,
        ):
            mcp_oauth._refresh_access_token(
                refresh,
                [mcp_oauth.MCP_PROMPTS_WRITE_SCOPE, mcp_oauth.MCP_MEMOS_READ_SCOPE],
            )

        self.assertEqual(context.exception.error, "invalid_scope")
        get_connection.assert_not_called()

    def test_refresh_can_narrow_an_existing_multi_scope_grant(self):
        refresh = self._refresh_token()
        refresh.scopes = list(mcp_oauth.MCP_ALLOWED_SCOPES)
        cursor = MagicMock()
        cursor.rowcount = 1

        @contextmanager
        def fake_connection():
            conn = MagicMock()
            conn.cursor.return_value = cursor
            yield conn

        with patch("services.mcp_oauth.get_db_connection", fake_connection):
            token = mcp_oauth._refresh_access_token(refresh, [mcp_oauth.MCP_MEMOS_READ_SCOPE])

        self.assertEqual(token.scope, mcp_oauth.MCP_MEMOS_READ_SCOPE)
        inserted_rows = cursor.executemany.call_args.args[1]
        self.assertEqual(inserted_rows[0][4], [mcp_oauth.MCP_MEMOS_READ_SCOPE])
        self.assertEqual(inserted_rows[1][4], [mcp_oauth.MCP_MEMOS_READ_SCOPE])

    def _load_refresh_row(self, replaced_at):
        return {
            "grant_id": uuid4(),
            "client_id": "mcp-personal-client",
            "scopes": [mcp_oauth.MCP_PROMPTS_WRITE_SCOPE],
            "resource": SERVER_URL,
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
            "replaced_at": replaced_at,
            "user_id": 7,
        }

    def test_refresh_reuse_within_grace_is_allowed(self):
        """回転直後（猶予期間内）の再利用は許容し、grant を失効させない。"""
        row = self._load_refresh_row(datetime.now(timezone.utc) - timedelta(seconds=5))
        cursor = MagicMock()
        cursor.fetchone.return_value = row

        @contextmanager
        def fake_connection():
            conn = MagicMock()
            conn.cursor.return_value = cursor
            yield conn

        with patch("services.mcp_oauth.get_mcp_server_url", return_value=SERVER_URL), patch(
            "services.mcp_oauth.get_db_connection", fake_connection
        ):
            result = mcp_oauth._load_refresh("mcp-personal-client", "refresh-token-value")

        self.assertIsNotNone(result)
        executed_sql = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
        self.assertNotIn("UPDATE mcp_oauth_grants SET revoked_at", executed_sql)

    def test_refresh_reuse_after_grace_revokes_grant_family(self):
        """猶予期間を過ぎた回転済みトークンの再利用は盗難とみなし、grant とトークンを失効させて None を返す。"""
        stale = datetime.now(timezone.utc) - timedelta(
            seconds=mcp_oauth.REFRESH_TOKEN_ROTATION_GRACE_SECONDS + 60
        )
        row = self._load_refresh_row(stale)
        cursor = MagicMock()
        cursor.fetchone.return_value = row

        @contextmanager
        def fake_connection():
            conn = MagicMock()
            conn.cursor.return_value = cursor
            yield conn

        with patch("services.mcp_oauth.get_db_connection", fake_connection):
            result = mcp_oauth._load_refresh("mcp-personal-client", "refresh-token-value")

        self.assertIsNone(result)
        executed_sql = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
        self.assertIn("UPDATE mcp_oauth_grants SET revoked_at = NOW()", executed_sql)
        self.assertIn("UPDATE mcp_oauth_tokens SET revoked_at = NOW()", executed_sql)

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

    def test_update_user_client_label_keeps_credential_active(self):
        cursor = MagicMock()
        cursor.rowcount = 1

        @contextmanager
        def fake_connection():
            conn = MagicMock()
            conn.cursor.return_value = cursor
            yield conn

        with patch("services.mcp_oauth.get_db_connection", fake_connection):
            updated = mcp_oauth.update_user_client_label(7, "mcp-personal-client", "仕事用")

        self.assertTrue(updated)
        executed_sql = cursor.execute.call_args.args[0]
        self.assertIn("UPDATE mcp_oauth_user_clients", executed_sql)
        self.assertNotIn("revoked_at = NOW()", executed_sql)
        self.assertEqual(cursor.execute.call_args.args[1], ("仕事用", "mcp-personal-client", 7))

    def test_update_connection_display_name_preserves_oauth_client_name(self):
        cursor = MagicMock()
        cursor.rowcount = 1

        @contextmanager
        def fake_connection():
            conn = MagicMock()
            conn.cursor.return_value = cursor
            yield conn

        with patch("services.mcp_oauth.get_db_connection", fake_connection):
            updated = mcp_oauth.update_connection_display_name(7, "grant-1", "個人用Claude")

        self.assertTrue(updated)
        executed_sql = cursor.execute.call_args.args[0]
        self.assertIn("SET display_name = %s", executed_sql)
        self.assertNotIn("client_name =", executed_sql)
        self.assertEqual(cursor.execute.call_args.args[1], ("個人用Claude", "grant-1", 7))

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
        self.assertEqual(stored_client["scope"], " ".join(mcp_oauth.MCP_ALLOWED_SCOPES))
        self.assertEqual(credentials["scopes"], list(mcp_oauth.MCP_ALLOWED_SCOPES))
        self.assertIsNone(stored_client.get("client_uri"))

    def test_issue_user_client_uses_a_public_client_without_a_secret(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"active": 0}

        @contextmanager
        def fake_connection():
            conn = MagicMock()
            conn.cursor.return_value = cursor
            yield conn

        with (
            patch("services.mcp_oauth._user_is_verified", return_value=True),
            patch("services.mcp_oauth.get_db_connection", fake_connection),
            patch("services.mcp_oauth.get_mcp_server_url", return_value=SERVER_URL),
        ):
            credentials = mcp_oauth.issue_user_client(
                7,
                "Public connector",
                "https://client.example.test/oauth/callback",
                issue_client_secret=False,
            )

        stored_client = json.loads(cursor.execute.call_args_list[2].args[1][1])
        self.assertIsNone(credentials["client_secret"])
        self.assertEqual(credentials["token_endpoint_auth_method"], "none")
        self.assertEqual(stored_client["token_endpoint_auth_method"], "none")
        self.assertIsNone(cursor.execute.call_args_list[2].args[1][2])

    def test_issue_user_client_keeps_optional_label_compatibility(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"active": 0}

        @contextmanager
        def fake_connection():
            conn = MagicMock()
            conn.cursor.return_value = cursor
            yield conn

        fernet = MagicMock()
        fernet.encrypt.return_value = b"encrypted-secret"
        with (
            patch("services.mcp_oauth._user_is_verified", return_value=True),
            patch("services.mcp_oauth.get_db_connection", fake_connection),
            patch("services.mcp_oauth._fernet", return_value=fernet),
            patch("services.mcp_oauth.get_mcp_server_url", return_value=SERVER_URL),
        ):
            credentials = mcp_oauth.issue_user_client(
                7,
                None,
                "https://client.example.test/oauth/callback",
            )

        stored_client = json.loads(cursor.execute.call_args_list[2].args[1][1])
        self.assertEqual(credentials["label"], "")
        self.assertEqual(stored_client["client_name"], "Personal Chat-Core connector")

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
            # RFC 8707 canonicalization treats scheme and host as case-insensitive.
            self.assertTrue(mcp_oauth._resource_matches_server("HTTPS://CHAT.EXAMPLE.TEST/mcp"))
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

    def test_authorize_accepts_any_registered_scope_subset(self):
        client = OAuthClientInformationFull(
            client_id="https://client.example.test/metadata.json",
            redirect_uris=["https://client.example.test/callback"],
            token_endpoint_auth_method="none",
            scope=" ".join(mcp_oauth.MCP_ALLOWED_SCOPES),
        )
        requested_scopes = [mcp_oauth.MCP_PROMPTS_READ_SCOPE, mcp_oauth.MCP_MEMOS_READ_SCOPE]
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
            asyncio.run(
                mcp_oauth.ChatCoreOAuthProvider().authorize(
                    client,
                    _make_params(None, requested_scopes),
                )
            )

        self.assertEqual(captured["payload"]["params"]["scopes"], requested_scopes)

    def test_authorize_without_scope_keeps_the_legacy_write_only_default(self):
        client = OAuthClientInformationFull(
            client_id="new-client",
            redirect_uris=["https://client.example.test/callback"],
            token_endpoint_auth_method="none",
            scope=" ".join(mcp_oauth.MCP_ALLOWED_SCOPES),
        )
        params = AuthorizationParams(
            state="state",
            scopes=None,
            code_challenge="challenge",
            redirect_uri="https://client.example.test/callback",
            redirect_uri_provided_explicitly=True,
            resource=None,
        )
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
            asyncio.run(mcp_oauth.ChatCoreOAuthProvider().authorize(client, params))

        self.assertEqual(
            captured["payload"]["params"]["scopes"],
            [mcp_oauth.MCP_PROMPTS_WRITE_SCOPE],
        )

    def test_authorize_rejects_scope_not_registered_for_client(self):
        client = OAuthClientInformationFull(
            client_id="legacy-client",
            redirect_uris=["https://client.example.test/callback"],
            token_endpoint_auth_method="none",
            scope=mcp_oauth.MCP_PROMPTS_WRITE_SCOPE,
        )
        with self.assertRaises(AuthorizeError) as context:
            asyncio.run(
                mcp_oauth.ChatCoreOAuthProvider().authorize(
                    client,
                    _make_params(None, [mcp_oauth.MCP_MEMOS_READ_SCOPE]),
                )
            )

        self.assertEqual(context.exception.error, "invalid_scope")

    def test_authorize_rejects_unknown_scope(self):
        client = OAuthClientInformationFull(
            client_id="client",
            redirect_uris=["https://client.example.test/callback"],
            token_endpoint_auth_method="none",
            scope=" ".join(mcp_oauth.MCP_ALLOWED_SCOPES),
        )
        with self.assertRaises(AuthorizeError) as context:
            asyncio.run(
                mcp_oauth.ChatCoreOAuthProvider().authorize(
                    client,
                    _make_params(None, ["admin:write"]),
                )
            )

        self.assertEqual(context.exception.error, "invalid_scope")

    def test_register_client_preserves_a_valid_scope_subset(self):
        client = OAuthClientInformationFull(
            client_id="dcr-client",
            redirect_uris=["https://client.example.test/callback"],
            token_endpoint_auth_method="none",
            scope=f"{mcp_oauth.MCP_PROMPTS_READ_SCOPE} {mcp_oauth.MCP_MEMOS_READ_SCOPE}",
        )
        store_client = AsyncMock()
        with patch("services.mcp_oauth.run_blocking", store_client):
            asyncio.run(mcp_oauth.ChatCoreOAuthProvider().register_client(client))

        self.assertEqual(
            client.scope,
            f"{mcp_oauth.MCP_PROMPTS_READ_SCOPE} {mcp_oauth.MCP_MEMOS_READ_SCOPE}",
        )
        store_client.assert_awaited_once_with(mcp_oauth._store_client, client)

    def test_register_client_without_scope_can_request_any_supported_subset(self):
        client = OAuthClientInformationFull(
            client_id="dcr-client",
            redirect_uris=["https://client.example.test/callback"],
            token_endpoint_auth_method="none",
        )
        with patch("services.mcp_oauth.run_blocking", new_callable=AsyncMock):
            asyncio.run(mcp_oauth.ChatCoreOAuthProvider().register_client(client))

        self.assertEqual(client.scope, " ".join(mcp_oauth.MCP_ALLOWED_SCOPES))

    def test_register_client_rejects_an_unknown_scope(self):
        client = OAuthClientInformationFull(
            client_id="dcr-client",
            redirect_uris=["https://client.example.test/callback"],
            token_endpoint_auth_method="none",
            scope="admin:write",
        )
        with self.assertRaises(mcp_oauth.RegistrationError) as context:
            asyncio.run(mcp_oauth.ChatCoreOAuthProvider().register_client(client))

        self.assertEqual(context.exception.error, "invalid_client_metadata")

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
