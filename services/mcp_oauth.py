"""OAuth provider and persistence used by Chat-Core's remote MCP endpoint."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import requests
from cryptography.fernet import Fernet, MultiFernet
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from services.async_utils import run_blocking
from services.db import get_db_connection
from services.mcp_config import get_mcp_encryption_keys, get_mcp_public_base_url, get_mcp_server_url
from services.runtime_config import get_session_secret_key
from services.url_fetcher import _pin_dns, _resolve_safe_ip

MCP_PROMPTS_WRITE_SCOPE = "prompts:write"
CLAUDE_CLIENT_PROVIDER = "claude"
CLAUDE_OAUTH_CALLBACK_URL = "https://claude.ai/api/mcp/auth_callback"
AUTHORIZATION_CODE_TTL_SECONDS = 300
ACCESS_TOKEN_TTL_SECONDS = 3600
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 3600
CONSENT_REQUEST_TTL_SECONDS = 600
MAX_CIMD_BYTES = 64 * 1024
MAX_CIMD_CACHE_SECONDS = 3600

_cimd_cache: dict[str, tuple[float, OAuthClientInformationFull]] = {}
logger = logging.getLogger(__name__)


class StoredAuthorizationCode(AuthorizationCode):
    grant_id: UUID


class StoredRefreshToken(RefreshToken):
    grant_id: UUID
    resource: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _serialize_client(client: OAuthClientInformationFull) -> dict[str, Any]:
    return client.model_dump(mode="json", exclude={"client_secret"})


def _parse_client(value: Any, secret: str | None = None) -> OAuthClientInformationFull:
    raw = json.loads(value) if isinstance(value, str) else dict(value)
    raw["client_secret"] = secret
    return OAuthClientInformationFull.model_validate(raw)


def _display_client_host(client: OAuthClientInformationFull, redirect_uri: str) -> str:
    """Resolve a display host even when an OAuth client uses an opaque client ID."""
    for candidate in (client.client_uri, client.client_id, redirect_uri):
        hostname = urlparse(str(candidate or "")).hostname
        if hostname:
            return hostname
    return "unknown"


def _fernet() -> MultiFernet:
    return MultiFernet([Fernet(key.encode("ascii")) for key in get_mcp_encryption_keys()])


def _consent_serializer() -> URLSafeTimedSerializer:
    secret = get_session_secret_key()
    if not secret:
        raise RuntimeError("FASTAPI_SECRET_KEY is required for MCP OAuth.")
    return URLSafeTimedSerializer(secret, salt="chat-core.mcp-oauth-consent")


def _resource_matches_server(requested: str | None) -> bool:
    """Check an RFC 8707 resource indicator against this MCP server.

    ChatGPT や一部のクライアントは認可リクエストで ``resource`` を送らないため、
    未指定は「このサーバー向け」とみなして許容する。指定された場合は、末尾スラッシュの
    有無を無視してこの MCP リソースを指しているときだけ受け付ける。
    """
    if not requested:
        return True
    return requested.rstrip("/") == get_mcp_server_url().rstrip("/")


def _validate_redirect_uris(client: OAuthClientInformationFull) -> None:
    for redirect_uri in client.redirect_uris or []:
        parsed = urlparse(str(redirect_uri))
        hostname = (parsed.hostname or "").lower()
        is_loopback = hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.fragment or not parsed.scheme or not parsed.netloc:
            raise RegistrationError("invalid_redirect_uri", "Redirect URI is invalid.")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
            raise RegistrationError(
                "invalid_redirect_uri",
                "Redirect URI must use HTTPS, except for loopback HTTP callbacks.",
            )


def _cimd_client(client_id: str) -> OAuthClientInformationFull | None:
    cached = _cimd_cache.get(client_id)
    now = _utc_now().timestamp()
    if cached and cached[0] > now:
        return cached[1]

    parsed = urlparse(client_id)
    if parsed.scheme != "https" or not parsed.netloc or not parsed.path:
        return None
    ip = _resolve_safe_ip(client_id)
    if ip is None or not parsed.hostname:
        return None
    try:
        with _pin_dns({parsed.hostname: ip}):
            response = requests.get(
                client_id,
                headers={"Accept": "application/json", "User-Agent": "Chat-Core-MCP/1.0"},
                timeout=10,
                allow_redirects=False,
                stream=True,
            )
            try:
                if response.status_code != 200:
                    return None
                content_type = response.headers.get("content-type", "").lower()
                if "json" not in content_type:
                    return None
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_content(chunk_size=8192, decode_unicode=False):
                    total += len(chunk)
                    if total > MAX_CIMD_BYTES:
                        return None
                    chunks.append(chunk)
                body = b"".join(chunks)
                data = json.loads(body.decode("utf-8"))
            finally:
                response.close()
        client = OAuthClientInformationFull.model_validate(data)
        if str(client.client_id) != client_id:
            return None
        if client.token_endpoint_auth_method not in {None, "none"}:
            return None
        client.token_endpoint_auth_method = "none"
        _validate_redirect_uris(client)
        _cimd_cache[client_id] = (now + MAX_CIMD_CACHE_SECONDS, client)
        return client
    except Exception:
        return None


def _load_registered_client(client_id: str) -> OAuthClientInformationFull | None:
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT c.metadata, c.client_secret_encrypted
                FROM mcp_oauth_clients c
                WHERE c.client_id = %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM mcp_oauth_user_clients uc
                      WHERE uc.client_id = c.client_id AND uc.revoked_at IS NOT NULL
                  )
                """,
                (client_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            encrypted = row.get("client_secret_encrypted")
            secret = _fernet().decrypt(str(encrypted).encode("ascii")).decode("utf-8") if encrypted else None
            return _parse_client(row["metadata"], secret)
        finally:
            cursor.close()


def _store_client(client: OAuthClientInformationFull) -> None:
    _validate_redirect_uris(client)
    encrypted = None
    if client.client_secret:
        encrypted = _fernet().encrypt(client.client_secret.encode("utf-8")).decode("ascii")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO mcp_oauth_clients (client_id, metadata, client_secret_encrypted, registration_method)
                VALUES (%s, %s::jsonb, %s, 'dcr')
                ON CONFLICT (client_id) DO NOTHING
                """,
                (str(client.client_id), json.dumps(_serialize_client(client)), encrypted),
            )
            conn.commit()
        finally:
            cursor.close()


def _user_client_is_authorized_for_user(client_id: str, user_id: int) -> bool:
    """Allow generic clients for every user and personal clients only for their owner."""
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT user_id, revoked_at
                FROM mcp_oauth_user_clients
                WHERE client_id = %s
                """,
                (client_id,),
            )
            row = cursor.fetchone()
            if not row:
                return True
            return row["revoked_at"] is None and int(row["user_id"]) == user_id
        finally:
            cursor.close()


def issue_claude_client(user_id: int) -> dict[str, str]:
    """Create a personal OAuth client for Claude's manual connector configuration.

    The secret is returned only to the caller so it can be shown once in the
    settings UI. The database keeps only its encrypted form.
    """
    if not _user_is_verified(user_id):
        raise ValueError("Only verified users can issue Claude credentials.")

    # クライアント ID には "claude" などのサービス名を含めず、他社サービスの
    # コネクターからでも流用できる中立的な識別子にする。
    # Keep the client ID vendor-neutral (no "claude") so it can also be reused
    # by non-Claude MCP connectors.
    client_id = f"mcp-{secrets.token_urlsafe(24)}"
    client_secret = secrets.token_urlsafe(48)
    client = OAuthClientInformationFull(
        client_id=client_id,
        client_secret=client_secret,
        client_name="Claude (personal Chat-Core connector)",
        client_uri="https://claude.ai",
        redirect_uris=[CLAUDE_OAUTH_CALLBACK_URL],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="client_secret_post",
        scope=MCP_PROMPTS_WRITE_SCOPE,
    )
    encrypted_secret = _fernet().encrypt(client_secret.encode("utf-8")).decode("ascii")

    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))
            cursor.execute(
                """
                SELECT client_id
                FROM mcp_oauth_user_clients
                WHERE user_id = %s AND provider = %s AND revoked_at IS NULL
                FOR UPDATE
                """,
                (user_id, CLAUDE_CLIENT_PROVIDER),
            )
            previous_client_ids = [str(row["client_id"]) for row in cursor.fetchall()]
            for previous_client_id in previous_client_ids:
                cursor.execute(
                    """
                    UPDATE mcp_oauth_grants SET revoked_at = NOW()
                    WHERE user_id = %s AND client_id = %s AND revoked_at IS NULL
                    """,
                    (user_id, previous_client_id),
                )
                cursor.execute(
                    """
                    UPDATE mcp_oauth_tokens t SET revoked_at = NOW()
                    FROM mcp_oauth_grants g
                    WHERE t.grant_id = g.id AND g.user_id = %s AND g.client_id = %s
                      AND t.revoked_at IS NULL
                    """,
                    (user_id, previous_client_id),
                )
            cursor.execute(
                """
                UPDATE mcp_oauth_user_clients SET revoked_at = NOW()
                WHERE user_id = %s AND provider = %s AND revoked_at IS NULL
                """,
                (user_id, CLAUDE_CLIENT_PROVIDER),
            )
            cursor.execute(
                """
                INSERT INTO mcp_oauth_clients (client_id, metadata, client_secret_encrypted, registration_method)
                VALUES (%s, %s::jsonb, %s, 'pre_registered')
                """,
                (client_id, json.dumps(_serialize_client(client)), encrypted_secret),
            )
            cursor.execute(
                """
                INSERT INTO mcp_oauth_user_clients (client_id, user_id, provider)
                VALUES (%s, %s, %s)
                """,
                (client_id, user_id, CLAUDE_CLIENT_PROVIDER),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": CLAUDE_OAUTH_CALLBACK_URL,
        "mcp_server_url": get_mcp_server_url(),
    }


def get_claude_client_status(user_id: int) -> dict[str, Any]:
    """Return personal-Claude client metadata without ever returning its secret."""
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT client_id, created_at
                FROM mcp_oauth_user_clients
                WHERE user_id = %s AND provider = %s AND revoked_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, CLAUDE_CLIENT_PROVIDER),
            )
            row = cursor.fetchone()
            if not row:
                return {"configured": False}
            return {
                "configured": True,
                "client_id": str(row["client_id"]),
                "created_at": row["created_at"].isoformat(),
                "redirect_uri": CLAUDE_OAUTH_CALLBACK_URL,
                "mcp_server_url": get_mcp_server_url(),
            }
        finally:
            cursor.close()


def _create_authorization_code(user_id: int, request_data: dict[str, Any]) -> str:
    raw_code = secrets.token_urlsafe(32)
    client = _parse_client(request_data["client"])
    params = request_data["params"]
    grant_id = uuid4()
    now = _utc_now()
    client_host = _display_client_host(client, params["redirect_uri"])
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO mcp_oauth_grants (id, user_id, client_id, client_name, client_host, scopes)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    str(grant_id),
                    user_id,
                    str(client.client_id),
                    client.client_name or str(client.client_id),
                    client_host,
                    params["scopes"],
                ),
            )
            cursor.execute(
                """
                INSERT INTO mcp_oauth_authorization_codes
                    (code_digest, grant_id, client_id, redirect_uri, code_challenge, scopes, resource, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    _digest(raw_code),
                    str(grant_id),
                    str(client.client_id),
                    params["redirect_uri"],
                    params["code_challenge"],
                    params["scopes"],
                    params["resource"],
                    now + timedelta(seconds=AUTHORIZATION_CODE_TTL_SECONDS),
                ),
            )
            conn.commit()
        finally:
            cursor.close()
    return raw_code


def _user_is_verified(user_id: int) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT is_verified FROM users WHERE id = %s", (user_id,))
            row = cursor.fetchone()
            return bool(row and row[0])
        finally:
            cursor.close()


def _issue_tokens(grant_id: UUID, client_id: str, scopes: list[str], resource: str) -> OAuthToken:
    access_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(32)
    now = _utc_now()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.executemany(
                """
                INSERT INTO mcp_oauth_tokens
                    (token_digest, grant_id, client_id, token_type, scopes, resource, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (_digest(access_token), str(grant_id), client_id, "access", scopes, resource, now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS)),
                    (_digest(refresh_token), str(grant_id), client_id, "refresh", scopes, resource, now + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS)),
                ],
            )
            cursor.execute("UPDATE mcp_oauth_grants SET last_used_at = NOW() WHERE id = %s", (str(grant_id),))
            conn.commit()
        finally:
            cursor.close()
    return OAuthToken(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_TTL_SECONDS,
        scope=" ".join(scopes),
    )


def _load_code(client_id: str, raw_code: str) -> StoredAuthorizationCode | None:
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT c.grant_id, c.client_id, c.redirect_uri, c.code_challenge, c.scopes,
                       c.resource, c.expires_at, g.user_id
                FROM mcp_oauth_authorization_codes c
                JOIN mcp_oauth_grants g ON g.id = c.grant_id
                WHERE c.code_digest = %s AND c.client_id = %s AND c.used_at IS NULL
                  AND c.expires_at > NOW() AND g.revoked_at IS NULL
                """,
                (_digest(raw_code), client_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return StoredAuthorizationCode(
                code=raw_code,
                client_id=client_id,
                scopes=list(row["scopes"]),
                expires_at=row["expires_at"].timestamp(),
                redirect_uri=row["redirect_uri"],
                redirect_uri_provided_explicitly=True,
                code_challenge=row["code_challenge"],
                resource=row["resource"],
                subject=str(row["user_id"]),
                grant_id=UUID(str(row["grant_id"])),
            )
        finally:
            cursor.close()


def _consume_code_and_issue(code: StoredAuthorizationCode) -> OAuthToken:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE mcp_oauth_authorization_codes SET used_at = NOW() WHERE code_digest = %s AND used_at IS NULL",
                (_digest(code.code),),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                raise TokenError("invalid_grant", "Authorization code was already used.")
            conn.commit()
        finally:
            cursor.close()
    return _issue_tokens(code.grant_id, code.client_id, code.scopes, code.resource or get_mcp_server_url())


def _load_refresh(client_id: str, raw_token: str) -> StoredRefreshToken | None:
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT t.grant_id, t.client_id, t.scopes, t.resource, t.expires_at, g.user_id
                FROM mcp_oauth_tokens t
                JOIN mcp_oauth_grants g ON g.id = t.grant_id
                JOIN users u ON u.id = g.user_id
                WHERE t.token_digest = %s AND t.client_id = %s AND t.token_type = 'refresh'
                  AND t.revoked_at IS NULL AND t.expires_at > NOW()
                  AND g.revoked_at IS NULL AND u.is_verified = TRUE
                """,
                (_digest(raw_token), client_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return StoredRefreshToken(
                token=raw_token,
                client_id=client_id,
                scopes=list(row["scopes"]),
                expires_at=int(row["expires_at"].timestamp()),
                subject=str(row["user_id"]),
                grant_id=UUID(str(row["grant_id"])),
                resource=row["resource"],
            )
        finally:
            cursor.close()


def _refresh_access_token(refresh: StoredRefreshToken, scopes: list[str]) -> OAuthToken:
    """Issue a fresh access token while keeping the same refresh token alive.

    リフレッシュトークンを回転（毎回失効させて発行し直す）させると、リフレッシュ要求の
    再試行や並行実行が発生したときに「既に使用済み」となって接続が切れ、外部サービスの
    コネクターを繰り返し再接続する必要が生じる。ここでは同じリフレッシュトークンを再利用可能
    のまま返し、使用のたびに有効期限を延長することで、一度接続したら切れないようにする。

    Instead of rotating (revoking and reissuing) the refresh token on every use,
    keep it reusable and simply roll its expiry forward. Rotation makes retried or
    concurrent refreshes fail as "already used", which drops the connection and
    forces users to reconnect their MCP connector; keeping the refresh token stable
    means a connection stays alive as long as it is used within the refresh TTL.
    """
    access_token = secrets.token_urlsafe(32)
    now = _utc_now()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE mcp_oauth_tokens
                SET expires_at = %s, last_used_at = NOW()
                WHERE token_digest = %s AND token_type = 'refresh' AND revoked_at IS NULL
                """,
                (now + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS), _digest(refresh.token)),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                raise TokenError("invalid_grant", "Refresh token is no longer valid.")
            cursor.execute(
                """
                INSERT INTO mcp_oauth_tokens
                    (token_digest, grant_id, client_id, token_type, scopes, resource, expires_at)
                VALUES (%s, %s, %s, 'access', %s, %s, %s)
                """,
                (
                    _digest(access_token),
                    str(refresh.grant_id),
                    refresh.client_id,
                    scopes,
                    refresh.resource,
                    now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
                ),
            )
            cursor.execute("UPDATE mcp_oauth_grants SET last_used_at = NOW() WHERE id = %s", (str(refresh.grant_id),))
            conn.commit()
        finally:
            cursor.close()
    return OAuthToken(
        access_token=access_token,
        refresh_token=refresh.token,
        expires_in=ACCESS_TOKEN_TTL_SECONDS,
        scope=" ".join(scopes),
    )


def _load_access(raw_token: str) -> AccessToken | None:
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT t.client_id, t.scopes, t.resource, t.expires_at, g.id AS grant_id, g.user_id
                FROM mcp_oauth_tokens t
                JOIN mcp_oauth_grants g ON g.id = t.grant_id
                JOIN users u ON u.id = g.user_id
                WHERE t.token_digest = %s AND t.token_type = 'access' AND t.revoked_at IS NULL
                  AND t.expires_at > NOW() AND g.revoked_at IS NULL AND u.is_verified = TRUE
                """,
                (_digest(raw_token),),
            )
            row = cursor.fetchone()
            if not row or row["resource"] != get_mcp_server_url():
                return None
            cursor.execute("UPDATE mcp_oauth_tokens SET last_used_at = NOW() WHERE token_digest = %s", (_digest(raw_token),))
            cursor.execute("UPDATE mcp_oauth_grants SET last_used_at = NOW() WHERE id = %s", (str(row["grant_id"]),))
            conn.commit()
            return AccessToken(
                token=raw_token,
                client_id=row["client_id"],
                scopes=list(row["scopes"]),
                expires_at=int(row["expires_at"].timestamp()),
                resource=row["resource"],
                subject=str(row["user_id"]),
            )
        finally:
            cursor.close()


class ChatCoreOAuthProvider(OAuthAuthorizationServerProvider[StoredAuthorizationCode, StoredRefreshToken, AccessToken]):
    """Official MCP SDK provider backed by Chat-Core's PostgreSQL database."""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        client = await run_blocking(_load_registered_client, client_id)
        if client is not None:
            return client
        return await run_blocking(_cimd_client, client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        method = client_info.token_endpoint_auth_method or "client_secret_post"
        if method not in {"none", "client_secret_post", "client_secret_basic"}:
            raise RegistrationError("invalid_client_metadata", "Unsupported token endpoint auth method.")
        await run_blocking(_store_client, client_info)

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        scopes = params.scopes or [MCP_PROMPTS_WRITE_SCOPE]
        if scopes != [MCP_PROMPTS_WRITE_SCOPE]:
            raise AuthorizeError("invalid_scope", "Only prompts:write for this MCP resource is available.")
        if not _resource_matches_server(params.resource):
            raise AuthorizeError(
                "invalid_request",
                "This authorization server only issues tokens for its own MCP resource.",
            )
        request_data = {
            "client": _serialize_client(client),
            "params": {
                "state": params.state,
                "scopes": scopes,
                "code_challenge": params.code_challenge,
                "redirect_uri": str(params.redirect_uri),
                # 認可コードには常に正規リソースを保存し、トークン発行・検証を一貫させる。
                # Persist the canonical resource so token issuance/validation stays consistent.
                "resource": get_mcp_server_url(),
            },
        }
        token = _consent_serializer().dumps(request_data)
        return f"{get_mcp_public_base_url()}/oauth/authorize?request={token}"

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> StoredAuthorizationCode | None:
        return await run_blocking(_load_code, str(client.client_id), authorization_code)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: StoredAuthorizationCode) -> OAuthToken:
        return await run_blocking(_consume_code_and_issue, authorization_code)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> StoredRefreshToken | None:
        return await run_blocking(_load_refresh, str(client.client_id), refresh_token)

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: StoredRefreshToken, scopes: list[str]) -> OAuthToken:
        return await run_blocking(_refresh_access_token, refresh_token, scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        return await run_blocking(_load_access, token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await run_blocking(revoke_token_value, token.token)


def read_consent_request(token: str) -> dict[str, Any] | None:
    try:
        return _consent_serializer().loads(token, max_age=CONSENT_REQUEST_TTL_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def consent_details(token: str) -> dict[str, Any] | None:
    request_data = read_consent_request(token)
    if not request_data:
        return None
    client = _parse_client(request_data["client"])
    redirect_host = urlparse(request_data["params"]["redirect_uri"]).hostname or ""
    return {
        "client_name": client.client_name or str(client.client_id),
        "client_id": str(client.client_id),
        "client_host": _display_client_host(client, request_data["params"]["redirect_uri"]),
        "redirect_host": redirect_host,
        "scope": MCP_PROMPTS_WRITE_SCOPE,
        "localhost_warning": redirect_host.lower() in {"localhost", "127.0.0.1", "::1"},
    }


def complete_consent(token: str, user_id: int, approved: bool) -> str | None:
    request_data = read_consent_request(token)
    if not request_data or not _user_is_verified(user_id):
        return None
    client_id = request_data.get("client", {}).get("client_id")
    if not isinstance(client_id, str) or not _user_client_is_authorized_for_user(client_id, user_id):
        logger.warning("Rejected MCP OAuth consent for a client not owned by user %s.", user_id)
        return None
    params = request_data["params"]
    if not approved:
        return construct_redirect_uri(params["redirect_uri"], error="access_denied", state=params.get("state"))
    code = _create_authorization_code(user_id, request_data)
    return construct_redirect_uri(params["redirect_uri"], code=code, state=params.get("state"))


def list_connections(user_id: int) -> list[dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT id, client_name, client_host, created_at, last_used_at
                FROM mcp_oauth_grants
                WHERE user_id = %s AND revoked_at IS NULL
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            return [
                {
                    **dict(row),
                    "id": str(row["id"]),
                    "created_at": row["created_at"].isoformat(),
                    "last_used_at": row["last_used_at"].isoformat() if row["last_used_at"] else None,
                }
                for row in rows
            ]
        finally:
            cursor.close()


def revoke_connection(user_id: int, grant_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE mcp_oauth_grants SET revoked_at = NOW()
                WHERE id = %s AND user_id = %s AND revoked_at IS NULL
                """,
                (grant_id, user_id),
            )
            updated = cursor.rowcount == 1
            if updated:
                cursor.execute("UPDATE mcp_oauth_tokens SET revoked_at = NOW() WHERE grant_id = %s AND revoked_at IS NULL", (grant_id,))
            conn.commit()
            return updated
        finally:
            cursor.close()


def revoke_token_value(raw_token: str) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE mcp_oauth_grants SET revoked_at = NOW()
                WHERE id = (SELECT grant_id FROM mcp_oauth_tokens WHERE token_digest = %s)
                  AND revoked_at IS NULL
                """,
                (_digest(raw_token),),
            )
            cursor.execute(
                """
                UPDATE mcp_oauth_tokens SET revoked_at = NOW()
                WHERE grant_id = (SELECT grant_id FROM mcp_oauth_tokens WHERE token_digest = %s)
                  AND revoked_at IS NULL
                """,
                (_digest(raw_token),),
            )
            conn.commit()
        finally:
            cursor.close()
