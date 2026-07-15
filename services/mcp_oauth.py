"""OAuth provider and persistence used by Chat-Core's remote MCP endpoint."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import partial
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
from services.mcp_config import (
    get_mcp_cimd_cache_entries,
    get_mcp_cimd_max_concurrent_fetches,
    get_mcp_encryption_keys,
    get_mcp_public_base_url,
    get_mcp_server_url,
)
from services.runtime_config import get_session_secret_key
from services.url_fetcher import _pin_dns, _resolve_safe_ip

MCP_PROMPTS_WRITE_SCOPE = "prompts:write"
MANUAL_CLIENT_PROVIDER = "manual"
DEFAULT_MCP_OAUTH_REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"
AUTHORIZATION_CODE_TTL_SECONDS = 300
ACCESS_TOKEN_TTL_SECONDS = 3600
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 3600
# 回転したリフレッシュトークンを直後の再試行・並行リフレッシュのために短時間だけ有効に保つ猶予期間。
# Grace window during which a just-rotated refresh token remains usable so that retried or
# concurrent refreshes succeed instead of breaking the connection.
REFRESH_TOKEN_ROTATION_GRACE_SECONDS = 60
CONSENT_REQUEST_TTL_SECONDS = 600
MAX_CIMD_BYTES = 64 * 1024
MAX_CIMD_CACHE_SECONDS = 3600
NEGATIVE_CIMD_CACHE_SECONDS = 300
MAX_USER_LABEL_LENGTH = 100
MAX_CLIENTS_PER_USER = 20
MAX_REDIRECT_URI_LENGTH = 2048

_cimd_cache: OrderedDict[str, tuple[float, OAuthClientInformationFull | None]] = OrderedDict()
_cimd_cache_lock = threading.Lock()
_cimd_executor_lock = threading.Lock()
_cimd_executor: ThreadPoolExecutor | None = None
_cimd_fetch_slots: threading.BoundedSemaphore | None = None
logger = logging.getLogger(__name__)


class ClientLimitReachedError(Exception):
    """Raised when a user already holds the maximum number of connector credentials."""


class InvalidRedirectUriError(ValueError):
    """Raised when a user-supplied OAuth redirect URI is unsafe or malformed."""


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

    def normalized_parts(value: str) -> tuple[str, str, int | None, str, str, str] | None:
        try:
            parsed = urlparse(value)
            port = parsed.port
        except ValueError:
            return None
        if (
            not parsed.scheme
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            return None
        return (
            parsed.scheme.lower(),
            parsed.hostname.lower(),
            port,
            parsed.path.rstrip("/"),
            parsed.params,
            parsed.query,
        )

    requested_parts = normalized_parts(requested)
    return requested_parts is not None and requested_parts == normalized_parts(get_mcp_server_url())


def _validate_redirect_uri(redirect_uri: str) -> None:
    try:
        parsed = urlparse(redirect_uri)
        port = parsed.port
    except ValueError as exc:
        raise RegistrationError("invalid_redirect_uri", "Redirect URI is invalid.") from exc
    hostname = (parsed.hostname or "").lower()
    is_loopback = hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        parsed.fragment
        or not parsed.scheme
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or port is not None and not 1 <= port <= 65535
    ):
        raise RegistrationError("invalid_redirect_uri", "Redirect URI is invalid.")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
        raise RegistrationError(
            "invalid_redirect_uri",
            "Redirect URI must use HTTPS, except for loopback HTTP callbacks.",
        )


def _validate_redirect_uris(client: OAuthClientInformationFull) -> None:
    for redirect_uri in client.redirect_uris or []:
        _validate_redirect_uri(str(redirect_uri))


def _clean_redirect_uri(redirect_uri: str | None) -> str:
    """Validate one callback URL supplied when creating a personal OAuth client."""
    if not isinstance(redirect_uri, str):
        raise InvalidRedirectUriError("コールバックURL（リダイレクトURI）が不正です。")
    cleaned = redirect_uri.strip()
    if not cleaned or len(cleaned) > MAX_REDIRECT_URI_LENGTH:
        raise InvalidRedirectUriError("コールバックURL（リダイレクトURI）が不正です。")
    try:
        _validate_redirect_uri(cleaned)
    except RegistrationError as exc:
        raise InvalidRedirectUriError("コールバックURL（リダイレクトURI）が不正です。") from exc
    return cleaned


def _get_cimd_executor() -> tuple[ThreadPoolExecutor, threading.BoundedSemaphore]:
    global _cimd_executor, _cimd_fetch_slots
    with _cimd_executor_lock:
        if _cimd_executor is None:
            max_workers = get_mcp_cimd_max_concurrent_fetches()
            _cimd_executor = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="chat-core-cimd",
            )
            _cimd_fetch_slots = threading.BoundedSemaphore(max_workers)
        if _cimd_fetch_slots is None:  # pragma: no cover - guarded by the branch above
            raise RuntimeError("CIMD fetch limiter was not initialized.")
        return _cimd_executor, _cimd_fetch_slots


def _read_cimd_cache(client_id: str, now: float) -> tuple[bool, OAuthClientInformationFull | None]:
    with _cimd_cache_lock:
        expired = [key for key, (expires_at, _) in _cimd_cache.items() if expires_at <= now]
        for key in expired:
            _cimd_cache.pop(key, None)
        cached = _cimd_cache.pop(client_id, None)
        if cached is None:
            return False, None
        _cimd_cache[client_id] = cached
        return True, cached[1]


def _write_cimd_cache(client_id: str, client: OAuthClientInformationFull | None, ttl_seconds: int) -> None:
    expires_at = _utc_now().timestamp() + ttl_seconds
    max_entries = get_mcp_cimd_cache_entries()
    with _cimd_cache_lock:
        _cimd_cache.pop(client_id, None)
        _cimd_cache[client_id] = (expires_at, client)
        while len(_cimd_cache) > max_entries:
            _cimd_cache.popitem(last=False)


def _cimd_client(client_id: str) -> OAuthClientInformationFull | None:
    now = _utc_now().timestamp()
    found, cached = _read_cimd_cache(client_id, now)
    if found:
        return cached

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
                    _write_cimd_cache(client_id, None, NEGATIVE_CIMD_CACHE_SECONDS)
                    return None
                content_type = response.headers.get("content-type", "").lower()
                if "json" not in content_type:
                    _write_cimd_cache(client_id, None, NEGATIVE_CIMD_CACHE_SECONDS)
                    return None
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_content(chunk_size=8192, decode_unicode=False):
                    total += len(chunk)
                    if total > MAX_CIMD_BYTES:
                        _write_cimd_cache(client_id, None, NEGATIVE_CIMD_CACHE_SECONDS)
                        return None
                    chunks.append(chunk)
                body = b"".join(chunks)
                data = json.loads(body.decode("utf-8"))
            finally:
                response.close()
        client = OAuthClientInformationFull.model_validate(data)
        if str(client.client_id) != client_id:
            _write_cimd_cache(client_id, None, NEGATIVE_CIMD_CACHE_SECONDS)
            return None
        if client.token_endpoint_auth_method not in {None, "none"}:
            _write_cimd_cache(client_id, None, NEGATIVE_CIMD_CACHE_SECONDS)
            return None
        client.token_endpoint_auth_method = "none"
        _validate_redirect_uris(client)
        _write_cimd_cache(client_id, client, MAX_CIMD_CACHE_SECONDS)
        return client
    except Exception:
        _write_cimd_cache(client_id, None, NEGATIVE_CIMD_CACHE_SECONDS)
        return None


async def _load_cimd_client(client_id: str) -> OAuthClientInformationFull | None:
    executor, slots = _get_cimd_executor()
    if not slots.acquire(blocking=False):
        logger.warning("Rejected CIMD metadata fetch because the concurrency limit is full.")
        return None
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(executor, partial(_cimd_client, client_id))
    finally:
        slots.release()


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


def _clean_user_label(label: str | None) -> str | None:
    """Normalize a user-managed label, or fall back to no label."""
    if not isinstance(label, str):
        return None
    cleaned = label.strip()
    if not cleaned:
        return None
    return cleaned[:MAX_USER_LABEL_LENGTH]


def issue_user_client(
    user_id: int,
    label: str | None = None,
    redirect_uri: str | None = None,
    issue_client_secret: bool = True,
) -> dict[str, str | None]:
    """Create a personal OAuth client credential for a manual connector setup.

    複数の認証情報を（サービスの API キーのように）保存できるように、既存の認証情報は
    失効させずに新しいものを追加する。シークレットが必要な場合だけ一度だけ呼び出し元へ
    返し、DB には暗号化した値だけを保存する。

    Unlike a single-credential model, this appends a new credential without
    revoking the user's existing ones, so several can be kept side by side. The
    secret is returned only to the caller when requested; the database keeps
    only its encrypted form.
    """
    if not _user_is_verified(user_id):
        raise ValueError("Only verified users can issue connector credentials.")

    cleaned_label = _clean_user_label(label)
    cleaned_redirect_uri = _clean_redirect_uri(
        DEFAULT_MCP_OAUTH_REDIRECT_URI if redirect_uri is None else redirect_uri
    )
    # クライアント ID には "claude" などのサービス名を含めず、他社サービスの
    # コネクターからでも流用できる中立的な識別子にする。
    # Keep the client ID vendor-neutral (no "claude") so it can also be reused
    # by non-Claude MCP connectors.
    client_id = f"mcp-{secrets.token_urlsafe(24)}"
    client_secret = secrets.token_urlsafe(48) if issue_client_secret else None
    try:
        client = OAuthClientInformationFull(
            client_id=client_id,
            client_secret=client_secret,
            client_name=cleaned_label or "Personal Chat-Core connector",
            redirect_uris=[cleaned_redirect_uri],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="client_secret_post" if client_secret else "none",
            scope=MCP_PROMPTS_WRITE_SCOPE,
        )
    except ValueError as exc:
        raise InvalidRedirectUriError("コールバックURL（リダイレクトURI）が不正です。") from exc
    _validate_redirect_uris(client)
    registered_redirect_uri = str(client.redirect_uris[0])
    encrypted_secret = (
        _fernet().encrypt(client_secret.encode("utf-8")).decode("ascii")
        if client_secret
        else None
    )

    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))
            cursor.execute(
                """
                SELECT COUNT(*) AS active
                FROM mcp_oauth_user_clients
                WHERE user_id = %s AND revoked_at IS NULL
                """,
                (user_id,),
            )
            active = int((cursor.fetchone() or {}).get("active", 0))
            if active >= MAX_CLIENTS_PER_USER:
                raise ClientLimitReachedError(
                    f"You can keep at most {MAX_CLIENTS_PER_USER} credentials."
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
                INSERT INTO mcp_oauth_user_clients (client_id, user_id, provider, label)
                VALUES (%s, %s, %s, %s)
                """,
                (client_id, user_id, MANUAL_CLIENT_PROVIDER, cleaned_label),
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
        "label": cleaned_label or "",
        "redirect_uri": registered_redirect_uri,
        "token_endpoint_auth_method": "client_secret_post" if client_secret else "none",
        "mcp_server_url": get_mcp_server_url(),
    }


def list_user_clients(user_id: int) -> dict[str, Any]:
    """List the user's saved connector credentials without ever exposing secrets."""
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT uc.client_id, uc.label, uc.created_at,
                       c.metadata -> 'redirect_uris' ->> 0 AS redirect_uri,
                       COALESCE(c.metadata ->> 'token_endpoint_auth_method', 'client_secret_post')
                           AS token_endpoint_auth_method
                FROM mcp_oauth_user_clients uc
                JOIN mcp_oauth_clients c ON c.client_id = uc.client_id
                WHERE uc.user_id = %s AND uc.revoked_at IS NULL
                ORDER BY uc.created_at DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            clients = [
                {
                    "client_id": str(row["client_id"]),
                    "label": row["label"] or "",
                    "redirect_uri": str(row["redirect_uri"]),
                    "token_endpoint_auth_method": str(row["token_endpoint_auth_method"]),
                    "created_at": row["created_at"].isoformat(),
                }
                for row in rows
            ]
            return {
                "clients": clients,
                "default_redirect_uri": DEFAULT_MCP_OAUTH_REDIRECT_URI,
                "mcp_server_url": get_mcp_server_url(),
            }
        finally:
            cursor.close()


def update_user_client_label(user_id: int, client_id: str, label: str) -> bool:
    """Update a personal credential's display label without rotating its secret."""
    cleaned_label = _clean_user_label(label)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE mcp_oauth_user_clients
                SET label = %s
                WHERE client_id = %s AND user_id = %s AND revoked_at IS NULL
                """,
                (cleaned_label, client_id, user_id),
            )
            updated = cursor.rowcount == 1
            conn.commit()
            return updated
        finally:
            cursor.close()


def revoke_user_client(user_id: int, client_id: str) -> bool:
    """Delete a saved credential and sever every connection made with it.

    認証情報を削除したら、その認証情報で確立済みの接続（grant とトークン）も同時に
    失効させ、外部サービス側の接続がすぐに切れるようにする。

    Revoking a credential also revokes the grants and tokens created with it, so
    the external connection stops working immediately.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE mcp_oauth_user_clients SET revoked_at = NOW()
                WHERE client_id = %s AND user_id = %s AND revoked_at IS NULL
                """,
                (client_id, user_id),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return False
            cursor.execute(
                """
                UPDATE mcp_oauth_tokens t SET revoked_at = NOW()
                FROM mcp_oauth_grants g
                WHERE t.grant_id = g.id AND g.user_id = %s AND g.client_id = %s
                  AND t.revoked_at IS NULL
                """,
                (user_id, client_id),
            )
            cursor.execute(
                """
                UPDATE mcp_oauth_grants SET revoked_at = NOW()
                WHERE user_id = %s AND client_id = %s AND revoked_at IS NULL
                """,
                (user_id, client_id),
            )
            conn.commit()
            return True
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


def _revoke_grant_family(cursor: Any, grant_id: str) -> None:
    """Revoke a grant and every token issued under it (refresh token reuse response)."""
    cursor.execute(
        "UPDATE mcp_oauth_grants SET revoked_at = NOW() WHERE id = %s AND revoked_at IS NULL",
        (grant_id,),
    )
    cursor.execute(
        "UPDATE mcp_oauth_tokens SET revoked_at = NOW() WHERE grant_id = %s AND revoked_at IS NULL",
        (grant_id,),
    )


def _load_refresh(client_id: str, raw_token: str) -> StoredRefreshToken | None:
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT t.grant_id, t.client_id, t.scopes, t.resource, t.expires_at, t.replaced_at, g.user_id
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
            replaced_at = row.get("replaced_at")
            if replaced_at is not None:
                # 既に回転済みのトークン。猶予期間内なら再試行・並行リフレッシュとして許容し、
                # 猶予を過ぎての再利用は盗難の兆候とみなして grant ごと失効させる。
                # A already-rotated token: tolerate reuse within the grace window (retry/concurrency),
                # but treat reuse after the window as a stolen-token signal and revoke the whole grant.
                if replaced_at <= _utc_now() - timedelta(seconds=REFRESH_TOKEN_ROTATION_GRACE_SECONDS):
                    _revoke_grant_family(cursor, str(row["grant_id"]))
                    conn.commit()
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
    """Rotate the refresh token and issue a fresh access token, with a reuse grace window.

    リフレッシュのたびにリフレッシュトークンを回転（新しい値を発行）させ、盗まれたトークンの
    悪用を検知できるようにする（public client 向けの OAuth 2.1 / RFC 9700 推奨）。
    ただし単純な回転だと再試行や並行リフレッシュが「使用済み」で失敗し接続が切れてしまうため、
    回転しても提示されたトークンを即失効させず ``replaced_at`` を立てて猶予期間だけ有効に保つ。
    猶予期間内の再利用は回転をやり直して新しいトークンを返すので、一度つないだら切れない。

    Rotate the refresh token on every use so a stolen refresh token can be detected
    (recommended for public clients by OAuth 2.1 / RFC 9700). A naive rotation would
    break connections when refreshes are retried or run concurrently, so instead of
    revoking the presented token immediately we mark it ``replaced_at`` and keep it
    valid for a short grace window. Reuse within the window simply rotates again and
    returns fresh tokens, so an established connection never drops.
    """
    new_refresh_token = secrets.token_urlsafe(32)
    access_token = secrets.token_urlsafe(32)
    now = _utc_now()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            # 提示されたトークンに回転マーカーを立てる。既に回転済み（猶予期間内の再試行）なら
            # 元の replaced_at を保ち猶予の起点を動かさない。
            # Mark the presented token as rotated. If it was already rotated (a retry within
            # the grace window), keep the original replaced_at so the grace clock does not reset.
            cursor.execute(
                """
                UPDATE mcp_oauth_tokens
                SET replaced_at = COALESCE(replaced_at, %s), last_used_at = NOW()
                WHERE token_digest = %s AND token_type = 'refresh' AND revoked_at IS NULL
                """,
                (now, _digest(refresh.token)),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                raise TokenError("invalid_grant", "Refresh token is no longer valid.")
            cursor.executemany(
                """
                INSERT INTO mcp_oauth_tokens
                    (token_digest, grant_id, client_id, token_type, scopes, resource, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        _digest(new_refresh_token),
                        str(refresh.grant_id),
                        refresh.client_id,
                        "refresh",
                        scopes,
                        refresh.resource,
                        now + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS),
                    ),
                    (
                        _digest(access_token),
                        str(refresh.grant_id),
                        refresh.client_id,
                        "access",
                        scopes,
                        refresh.resource,
                        now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
                    ),
                ],
            )
            cursor.execute("UPDATE mcp_oauth_grants SET last_used_at = NOW() WHERE id = %s", (str(refresh.grant_id),))
            conn.commit()
        finally:
            cursor.close()
    return OAuthToken(
        access_token=access_token,
        refresh_token=new_refresh_token,
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
        return await _load_cimd_client(client_id)

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
                SELECT id, client_name, client_host, display_name, created_at, last_used_at
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


def update_connection_display_name(user_id: int, grant_id: str, display_name: str) -> bool:
    """Set a user-facing alias while retaining the OAuth client's original name."""
    cleaned_name = _clean_user_label(display_name)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE mcp_oauth_grants
                SET display_name = %s
                WHERE id = %s AND user_id = %s AND revoked_at IS NULL
                """,
                (cleaned_name, grant_id, user_id),
            )
            updated = cursor.rowcount == 1
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
