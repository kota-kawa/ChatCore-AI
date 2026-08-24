import asyncio
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from mcp.server.auth.provider import AuthorizationParams, AuthorizeError
from mcp.shared.auth import InvalidRedirectUriError as McpInvalidRedirectUriError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from services import mcp_oauth


SERVER_URL = "https://chat.example.test/mcp"


@asynccontextmanager
async def _session_scope():
    class _Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    class _Session:
        def begin(self):
            return _Transaction()

    yield _Session()


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
    def test_cimd_client_accepts_claude_code_ephemeral_loopback_port(self):
        client = mcp_oauth.CimdOAuthClientInformation(
            client_id="https://claude.ai/oauth/client-metadata",
            redirect_uris=["http://localhost/callback", "http://127.0.0.1/callback"],
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

    def test_consent_details_exposes_each_requested_scope_and_label(self):
        client = OAuthClientInformationFull(
            client_id="https://client.example.test/metadata.json",
            redirect_uris=["https://client.example.test/callback"],
            client_name="Example AI",
            token_endpoint_auth_method="none",
        )
        scopes = [
            mcp_oauth.MCP_PROMPTS_READ_SCOPE,
            mcp_oauth.MCP_MEMOS_READ_SCOPE,
            mcp_oauth.MCP_MEMOS_WRITE_SCOPE,
        ]
        payload = {
            "client": mcp_oauth._serialize_client(client),
            "params": {
                "state": "state",
                "scopes": scopes,
                "code_challenge": "challenge",
                "redirect_uri": "https://client.example.test/callback",
                "resource": SERVER_URL,
            },
        }
        with patch("services.mcp_oauth.get_session_secret_key", return_value="test-secret"):
            token = mcp_oauth._consent_serializer().dumps(payload)
            details = mcp_oauth.consent_details(token)

        self.assertEqual(details["scope"], " ".join(scopes))
        self.assertEqual(details["scopes"], scopes)
        self.assertEqual(details["client_host"], "client.example.test")
        self.assertEqual(
            details["scope_labels"][mcp_oauth.MCP_MEMOS_READ_SCOPE],
            "保存したメモを検索・閲覧する",
        )

    def test_registered_client_reads_the_client_metadata_orm_attribute(self):
        metadata = {
            "client_id": "dcr-client",
            "redirect_uris": ["https://client.example.test/callback"],
            "token_endpoint_auth_method": "none",
        }
        repository = MagicMock()
        repository.load_registered_client = AsyncMock(
            return_value=SimpleNamespace(
                client_metadata=metadata,
                client_secret_encrypted=None,
            )
        )
        with (
            patch("services.mcp_oauth.session_scope", new=_session_scope),
            patch("services.mcp_oauth._oauth_repository", repository),
        ):
            client = asyncio.run(mcp_oauth._load_registered_client("dcr-client"))

        self.assertEqual(str(client.client_id), "dcr-client")
        repository.load_registered_client.assert_awaited_once()

    def _refresh_token(self, scopes=None, grant_id=None):
        return mcp_oauth.StoredRefreshToken(
            token="refresh-token-value",
            client_id="mcp-personal-client",
            scopes=scopes or [mcp_oauth.MCP_PROMPTS_WRITE_SCOPE],
            expires_at=9999999999,
            subject="7",
            grant_id=grant_id or uuid4(),
            resource=SERVER_URL,
        )

    def _refresh_record(self, *, replaced_at=None, scope_version=None):
        token = SimpleNamespace(
            grant_id=uuid4(),
            client_id="mcp-personal-client",
            scopes=[mcp_oauth.MCP_PROMPTS_WRITE_SCOPE],
            resource=SERVER_URL,
            replaced_at=replaced_at,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        return SimpleNamespace(
            token=token,
            user_id=7,
            scope_version=scope_version or mcp_oauth.MCP_OAUTH_SCOPE_VERSION,
        )

    def test_refresh_rotates_under_one_locked_async_transaction(self):
        refresh = self._refresh_token()
        record = self._refresh_record()
        repository = MagicMock()
        repository.load_refresh_token = AsyncMock(return_value=record)
        repository.mark_refresh_rotated = AsyncMock(return_value=True)
        repository.insert_tokens = AsyncMock()

        with (
            patch("services.mcp_oauth.session_scope", new=_session_scope),
            patch("services.mcp_oauth._oauth_repository", repository),
        ):
            token = asyncio.run(
                mcp_oauth._refresh_access_token(
                    refresh, [mcp_oauth.MCP_PROMPTS_WRITE_SCOPE]
                )
            )

        self.assertTrue(token.refresh_token)
        self.assertNotEqual(token.refresh_token, refresh.token)
        self.assertNotEqual(token.access_token, token.refresh_token)
        repository.load_refresh_token.assert_awaited_once()
        self.assertTrue(repository.load_refresh_token.await_args.kwargs["for_update"])
        repository.mark_refresh_rotated.assert_awaited_once()
        repository.insert_tokens.assert_awaited_once()

    def test_refresh_rejects_scope_escalation_before_opening_a_session(self):
        refresh = self._refresh_token()
        session_scope = MagicMock()
        with (
            patch("services.mcp_oauth.session_scope", session_scope),
            self.assertRaises(mcp_oauth.TokenError) as context,
        ):
            asyncio.run(
                mcp_oauth._refresh_access_token(
                    refresh,
                    [
                        mcp_oauth.MCP_PROMPTS_WRITE_SCOPE,
                        mcp_oauth.MCP_MEMOS_READ_SCOPE,
                    ],
                )
            )

        self.assertEqual(context.exception.error, "invalid_scope")
        session_scope.assert_not_called()

    def test_refresh_can_narrow_an_existing_multi_scope_grant(self):
        scopes = list(mcp_oauth.MCP_ALLOWED_SCOPES)
        refresh = self._refresh_token(scopes=scopes)
        record = self._refresh_record()
        repository = MagicMock()
        repository.load_refresh_token = AsyncMock(return_value=record)
        repository.mark_refresh_rotated = AsyncMock(return_value=True)
        repository.insert_tokens = AsyncMock()
        with (
            patch("services.mcp_oauth.session_scope", new=_session_scope),
            patch("services.mcp_oauth._oauth_repository", repository),
        ):
            token = asyncio.run(
                mcp_oauth._refresh_access_token(
                    refresh, [mcp_oauth.MCP_MEMOS_READ_SCOPE]
                )
            )

        self.assertEqual(token.scope, mcp_oauth.MCP_MEMOS_READ_SCOPE)
        self.assertEqual(
            repository.insert_tokens.await_args.kwargs["scopes"],
            [mcp_oauth.MCP_MEMOS_READ_SCOPE],
        )

    def test_legacy_refresh_grant_is_revoked_and_requires_reauthorization(self):
        repository = MagicMock()
        repository.load_refresh_token = AsyncMock(
            return_value=self._refresh_record(
                scope_version=mcp_oauth.MCP_OAUTH_SCOPE_VERSION - 1
            )
        )
        repository.revoke_grant_family = AsyncMock()
        with (
            patch("services.mcp_oauth.session_scope", new=_session_scope),
            patch("services.mcp_oauth._oauth_repository", repository),
        ):
            result = asyncio.run(
                mcp_oauth._load_refresh("mcp-personal-client", "refresh-token-value")
            )

        self.assertIsNone(result)
        repository.revoke_grant_family.assert_awaited_once()

    def test_refresh_reuse_within_grace_is_allowed(self):
        repository = MagicMock()
        repository.load_refresh_token = AsyncMock(
            return_value=self._refresh_record(
                replaced_at=datetime.now(timezone.utc) - timedelta(seconds=5)
            )
        )
        repository.revoke_grant_family = AsyncMock()
        with (
            patch("services.mcp_oauth.session_scope", new=_session_scope),
            patch("services.mcp_oauth._oauth_repository", repository),
        ):
            result = asyncio.run(
                mcp_oauth._load_refresh("mcp-personal-client", "refresh-token-value")
            )

        self.assertIsNotNone(result)
        repository.revoke_grant_family.assert_not_awaited()

    def test_refresh_reuse_after_grace_revokes_grant_family(self):
        repository = MagicMock()
        repository.load_refresh_token = AsyncMock(
            return_value=self._refresh_record(
                replaced_at=datetime.now(timezone.utc)
                - timedelta(
                    seconds=mcp_oauth.REFRESH_TOKEN_ROTATION_GRACE_SECONDS + 60
                )
            )
        )
        repository.revoke_grant_family = AsyncMock()
        with (
            patch("services.mcp_oauth.session_scope", new=_session_scope),
            patch("services.mcp_oauth._oauth_repository", repository),
        ):
            result = asyncio.run(
                mcp_oauth._load_refresh("mcp-personal-client", "refresh-token-value")
            )

        self.assertIsNone(result)
        repository.revoke_grant_family.assert_awaited_once()

    def test_legacy_access_grant_is_revoked(self):
        repository = MagicMock()
        repository.load_access_token = AsyncMock(
            return_value=SimpleNamespace(
                token=SimpleNamespace(resource=SERVER_URL),
                grant_id=uuid4(),
                user_id=7,
                scope_version=mcp_oauth.MCP_OAUTH_SCOPE_VERSION - 1,
            )
        )
        repository.revoke_grant_family = AsyncMock()
        with (
            patch("services.mcp_oauth.session_scope", new=_session_scope),
            patch("services.mcp_oauth._oauth_repository", repository),
            patch("services.mcp_oauth.get_mcp_server_url", return_value=SERVER_URL),
        ):
            result = asyncio.run(mcp_oauth._load_access("legacy-access-token"))

        self.assertIsNone(result)
        repository.revoke_grant_family.assert_awaited_once()

    def test_revoke_and_label_updates_are_async_repository_calls(self):
        repository = MagicMock()
        repository.revoke_user_client = AsyncMock(return_value=True)
        repository.update_user_client_label = AsyncMock(return_value=True)
        repository.update_connection_display_name = AsyncMock(return_value=True)
        with (
            patch("services.mcp_oauth.session_scope", new=_session_scope),
            patch("services.mcp_oauth._oauth_repository", repository),
        ):
            self.assertTrue(
                asyncio.run(mcp_oauth.revoke_user_client(7, "mcp-personal-client"))
            )
            self.assertTrue(
                asyncio.run(
                    mcp_oauth.update_user_client_label(7, "mcp-personal-client", "仕事用")
                )
            )
            self.assertTrue(
                asyncio.run(
                    mcp_oauth.update_connection_display_name(7, str(uuid4()), "個人用AI")
                )
            )

        repository.revoke_user_client.assert_awaited_once()
        repository.update_user_client_label.assert_awaited_once()
        repository.update_connection_display_name.assert_awaited_once()

    def test_issue_user_client_locks_user_before_enforcing_limit(self):
        repository = MagicMock()
        repository.lock_user = AsyncMock(return_value=SimpleNamespace(is_verified=True))
        repository.count_active_user_clients = AsyncMock(return_value=0)
        repository.insert_personal_client = AsyncMock()
        fernet = MagicMock()
        fernet.encrypt.return_value = b"encrypted-secret"
        with (
            patch("services.mcp_oauth.session_scope", new=_session_scope),
            patch("services.mcp_oauth._oauth_repository", repository),
            patch("services.mcp_oauth._user_is_verified", new=AsyncMock(return_value=True)),
            patch("services.mcp_oauth._fernet", return_value=fernet),
            patch("services.mcp_oauth.get_mcp_server_url", return_value=SERVER_URL),
        ):
            credentials = asyncio.run(
                mcp_oauth.issue_user_client(
                    7, "Example AI", "https://client.example.test/oauth/callback"
                )
            )

        self.assertEqual(credentials["redirect_uri"], "https://client.example.test/oauth/callback")
        metadata = repository.insert_personal_client.await_args.kwargs["metadata"]
        self.assertEqual(metadata["redirect_uris"], ["https://client.example.test/oauth/callback"])
        self.assertEqual(metadata["client_name"], "Example AI")
        repository.lock_user.assert_awaited_once()
        repository.count_active_user_clients.assert_awaited_once()

    def test_issue_user_client_can_be_public_without_secret(self):
        repository = MagicMock()
        repository.lock_user = AsyncMock(return_value=SimpleNamespace(is_verified=True))
        repository.count_active_user_clients = AsyncMock(return_value=0)
        repository.insert_personal_client = AsyncMock()
        with (
            patch("services.mcp_oauth.session_scope", new=_session_scope),
            patch("services.mcp_oauth._oauth_repository", repository),
            patch("services.mcp_oauth._user_is_verified", new=AsyncMock(return_value=True)),
            patch("services.mcp_oauth.get_mcp_server_url", return_value=SERVER_URL),
        ):
            credentials = asyncio.run(
                mcp_oauth.issue_user_client(
                    7,
                    None,
                    "https://client.example.test/oauth/callback",
                    issue_client_secret=False,
                )
            )

        self.assertIsNone(credentials["client_secret"])
        self.assertEqual(credentials["token_endpoint_auth_method"], "none")

    def test_redirect_validation_rejects_non_loopback_http(self):
        client = OAuthClientInformationFull(
            client_id="client",
            redirect_uris=["http://example.test/callback"],
            token_endpoint_auth_method="none",
        )
        with self.assertRaises(mcp_oauth.RegistrationError):
            mcp_oauth._validate_redirect_uris(client)

    def test_resource_matches_server_accepts_missing_or_canonical(self):
        with patch("services.mcp_oauth.get_mcp_server_url", return_value=SERVER_URL):
            self.assertTrue(mcp_oauth._resource_matches_server(None))
            self.assertTrue(mcp_oauth._resource_matches_server(SERVER_URL + "/"))
            self.assertFalse(
                mcp_oauth._resource_matches_server("https://evil.example.test/mcp")
            )

    def test_authorize_accepts_registered_scope_subset_and_canonical_resource(self):
        client = OAuthClientInformationFull(
            client_id="new-client",
            redirect_uris=["https://client.example.test/callback"],
            token_endpoint_auth_method="none",
            scope=" ".join(mcp_oauth.MCP_ALLOWED_SCOPES),
        )
        captured = {}

        def fake_dumps(payload):
            captured["payload"] = payload
            return "signed-token"

        with (
            patch("services.mcp_oauth.get_mcp_server_url", return_value=SERVER_URL),
            patch(
                "services.mcp_oauth.get_mcp_public_base_url",
                return_value="https://chat.example.test",
            ),
            patch("services.mcp_oauth._consent_serializer") as serializer,
        ):
            serializer.return_value.dumps.side_effect = fake_dumps
            redirect = asyncio.run(
                mcp_oauth.ChatCoreOAuthProvider().authorize(
                    client,
                    _make_params(None, [mcp_oauth.MCP_MEMOS_READ_SCOPE]),
                )
            )

        self.assertEqual(
            redirect,
            "https://chat.example.test/oauth/authorize?request=signed-token",
        )
        self.assertEqual(
            captured["payload"]["params"]["scopes"],
            [mcp_oauth.MCP_MEMOS_READ_SCOPE],
        )
        self.assertEqual(captured["payload"]["params"]["resource"], SERVER_URL)

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
                    client, _make_params(None, [mcp_oauth.MCP_MEMOS_READ_SCOPE])
                )
            )
        self.assertEqual(context.exception.error, "invalid_scope")

    def test_register_client_awaits_async_persistence(self):
        client = OAuthClientInformationFull(
            client_id="dcr-client",
            redirect_uris=["https://client.example.test/callback"],
            token_endpoint_auth_method="none",
            scope=f"{mcp_oauth.MCP_PROMPTS_READ_SCOPE} {mcp_oauth.MCP_MEMOS_READ_SCOPE}",
        )
        store_client = AsyncMock()
        with patch("services.mcp_oauth._store_client", new=store_client):
            asyncio.run(mcp_oauth.ChatCoreOAuthProvider().register_client(client))

        self.assertEqual(
            client.scope,
            f"{mcp_oauth.MCP_PROMPTS_READ_SCOPE} {mcp_oauth.MCP_MEMOS_READ_SCOPE}",
        )
        store_client.assert_awaited_once_with(client)

    def test_complete_consent_awaits_authorization_code_creation(self):
        request_data = {
            "client": {"client_id": "personal-client"},
            "params": {
                "scopes": [mcp_oauth.MCP_PROMPTS_WRITE_SCOPE],
                "code_challenge": "challenge",
                "resource": SERVER_URL,
                "redirect_uri": "https://client.example.test/callback",
                "state": "state",
            },
        }
        create_code = AsyncMock(return_value="authorization-code")
        with (
            patch("services.mcp_oauth.read_consent_request", return_value=request_data),
            patch("services.mcp_oauth._user_is_verified", new=AsyncMock(return_value=True)),
            patch(
                "services.mcp_oauth._user_client_is_authorized_for_user",
                new=AsyncMock(return_value=True),
            ),
            patch("services.mcp_oauth._create_authorization_code", new=create_code),
        ):
            redirect = asyncio.run(
                mcp_oauth.complete_consent("signed-request", user_id=7, approved=True)
            )

        self.assertEqual(
            redirect,
            "https://client.example.test/callback?code=authorization-code&state=state",
        )
        create_code.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
