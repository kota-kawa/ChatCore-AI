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
from mcp.shared.auth import (
    InvalidRedirectUriError as McpInvalidRedirectUriError,
    OAuthClientInformationFull,
    OAuthToken,
)
from pydantic import AnyUrl

from services.db import session_scope
from services.mcp_config import (
    get_mcp_cimd_cache_entries,
    get_mcp_cimd_max_concurrent_fetches,
    get_mcp_encryption_keys,
    get_mcp_public_base_url,
    get_mcp_server_url,
)
from services.runtime_config import get_session_secret_key
from services.url_fetcher import _pin_dns, _resolve_safe_ip
from services.repositories.mcp_oauth_repository import (
    McpOAuthRepository,
)

MCP_PROMPTS_READ_SCOPE = "prompts:read"
MCP_PROMPTS_WRITE_SCOPE = "prompts:write"
MCP_MEMOS_READ_SCOPE = "memos:read"
MCP_MEMOS_WRITE_SCOPE = "memos:write"
MCP_CONTEXT_READ_SCOPE = "context:read"
MCP_CONTEXT_WRITE_SCOPE = "context:write"
MCP_ALLOWED_SCOPES = (
    MCP_PROMPTS_READ_SCOPE,
    MCP_PROMPTS_WRITE_SCOPE,
    MCP_MEMOS_READ_SCOPE,
    MCP_MEMOS_WRITE_SCOPE,
    MCP_CONTEXT_READ_SCOPE,
    MCP_CONTEXT_WRITE_SCOPE,
)
# Newly registered clients need to be able to request any supported subset.
# Authorization requests that omit ``scope`` use the scopes registered for
# that client. Existing grants keep their persisted scopes and therefore never
# gain access merely because the server's supported scope set grows.
MCP_DEFAULT_SCOPES = MCP_ALLOWED_SCOPES
MCP_OAUTH_SCOPE_VERSION = 2
MCP_SCOPE_LABELS = {
    MCP_PROMPTS_READ_SCOPE: "公開プロンプトとSKILLを検索・閲覧する",
    MCP_PROMPTS_WRITE_SCOPE: "公開プロンプトを投稿する",
    MCP_MEMOS_READ_SCOPE: "保存したメモを検索・閲覧する",
    MCP_MEMOS_WRITE_SCOPE: "保存したメモを編集する",
    MCP_CONTEXT_READ_SCOPE: "パーソナル・コンテキストを読み取る",
    MCP_CONTEXT_WRITE_SCOPE: "パーソナル・コンテキストを保存・編集する",
}
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
_oauth_repository = McpOAuthRepository()


class ClientLimitReachedError(Exception):
    """Raised when a user already holds the maximum number of connector credentials."""


class InvalidRedirectUriError(ValueError):
    """Raised when a user-supplied OAuth redirect URI is unsafe or malformed."""


def _loopback_redirect_uris_match(registered: str, requested: str) -> bool:
    """Match native-client loopback callbacks while ignoring the ephemeral port."""
    try:
        registered_url = urlparse(registered)
        requested_url = urlparse(requested)
        registered_url.port
        requested_url.port
    except ValueError:
        return False

    loopback_hosts = {"localhost", "127.0.0.1", "::1"}
    registered_host = (registered_url.hostname or "").lower()
    requested_host = (requested_url.hostname or "").lower()
    if (
        registered_url.scheme.lower() != "http"
        or requested_url.scheme.lower() != "http"
        or registered_host not in loopback_hosts
        or requested_host != registered_host
        or registered_url.username is not None
        or registered_url.password is not None
        or requested_url.username is not None
        or requested_url.password is not None
    ):
        return False
    return (
        registered_url.path,
        registered_url.params,
        registered_url.query,
        registered_url.fragment,
    ) == (
        requested_url.path,
        requested_url.params,
        requested_url.query,
        requested_url.fragment,
    )


class CimdOAuthClientInformation(OAuthClientInformationFull):
    """CIMD client metadata with RFC 8252 loopback redirect compatibility."""

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        try:
            return super().validate_redirect_uri(redirect_uri)
        except McpInvalidRedirectUriError:
            if redirect_uri is not None and any(
                _loopback_redirect_uris_match(str(registered), str(redirect_uri))
                for registered in self.redirect_uris or []
            ):
                return redirect_uri
            raise


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


def _normalize_scopes(
    scopes: list[str] | tuple[str, ...] | None,
    *,
    default: tuple[str, ...] = MCP_DEFAULT_SCOPES,
) -> list[str]:
    """Validate an OAuth scope subset while preserving the requested order."""
    requested = list(default if scopes is None else scopes)
    normalized: list[str] = []
    for scope in requested:
        if not isinstance(scope, str) or scope not in MCP_ALLOWED_SCOPES:
            raise ValueError(f"Unsupported MCP OAuth scope: {scope}")
        if scope not in normalized:
            normalized.append(scope)
    if not normalized:
        raise ValueError("At least one MCP OAuth scope is required.")
    return normalized


def _normalize_client_scope(
    scope: str | None,
    *,
    default: tuple[str, ...] = MCP_DEFAULT_SCOPES,
) -> str:
    requested = scope.split() if isinstance(scope, str) and scope.strip() else list(default)
    return " ".join(_normalize_scopes(requested, default=default))


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
        client = CimdOAuthClientInformation.model_validate(data)
        if str(client.client_id) != client_id:
            _write_cimd_cache(client_id, None, NEGATIVE_CIMD_CACHE_SECONDS)
            return None
        if client.token_endpoint_auth_method not in {None, "none"}:
            _write_cimd_cache(client_id, None, NEGATIVE_CIMD_CACHE_SECONDS)
            return None
        client.token_endpoint_auth_method = "none"
        # CIMD metadata is client-global and normally cannot name this server's
        # private scopes. The authorization server owns the allowed scope set;
        # make it available to the SDK's client-level validation before the
        # provider applies its own strict scope check in authorize().
        client.scope = " ".join(MCP_ALLOWED_SCOPES)
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


async def _load_registered_client(client_id: str) -> OAuthClientInformationFull | None:
    async with session_scope() as session:
        row = await _oauth_repository.load_registered_client(session, client_id)
        if row is None:
            return None
        encrypted = row.client_secret_encrypted
        secret = (
            _fernet().decrypt(str(encrypted).encode("ascii")).decode("utf-8")
            if encrypted
            else None
        )
        # ``client_metadata`` is the ORM attribute for the physical JSONB
        # column named ``metadata``.  Do not access Base.metadata here.
        return _parse_client(row.client_metadata, secret)


async def _store_client(client: OAuthClientInformationFull) -> None:
    _validate_redirect_uris(client)
    try:
        client.scope = _normalize_client_scope(client.scope)
    except ValueError as exc:
        raise RegistrationError(
            "invalid_client_metadata", "Requested OAuth scopes are not supported."
        ) from exc
    encrypted = None
    if client.client_secret:
        encrypted = _fernet().encrypt(client.client_secret.encode("utf-8")).decode("ascii")
    async with session_scope() as session:
        async with session.begin():
            await _oauth_repository.store_client(
                session,
                client_id=str(client.client_id),
                metadata=_serialize_client(client),
                encrypted_secret=encrypted,
                registration_method="dcr",
            )


async def _user_client_is_authorized_for_user(client_id: str, user_id: int) -> bool:
    """Allow generic clients for every user and personal clients only for their owner."""
    async with session_scope() as session:
        return await _oauth_repository.user_client_is_authorized(session, client_id, user_id)


def _clean_user_label(label: str | None) -> str | None:
    """Normalize a user-managed label, or fall back to no label."""
    if not isinstance(label, str):
        return None
    cleaned = label.strip()
    if not cleaned:
        return None
    return cleaned[:MAX_USER_LABEL_LENGTH]


async def issue_user_client(
    user_id: int,
    label: str | None = None,
    redirect_uri: str | None = None,
    issue_client_secret: bool = True,
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    """Create a personal OAuth client credential for a manual connector setup.

    複数の認証情報を（サービスの API キーのように）保存できるように、既存の認証情報は
    失効させずに新しいものを追加する。シークレットが必要な場合だけ一度だけ呼び出し元へ
    返し、DB には暗号化した値だけを保存する。

    Unlike a single-credential model, this appends a new credential without
    revoking the user's existing ones, so several can be kept side by side. The
    secret is returned only to the caller when requested; the database keeps
    only its encrypted form.
    """
    if not await _user_is_verified(user_id):
        raise ValueError("Only verified users can issue connector credentials.")

    cleaned_label = _clean_user_label(label)
    cleaned_redirect_uri = _clean_redirect_uri(
        DEFAULT_MCP_OAUTH_REDIRECT_URI if redirect_uri is None else redirect_uri
    )
    client_scopes = _normalize_scopes(
        scopes,
        default=MCP_ALLOWED_SCOPES,
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
            scope=" ".join(client_scopes),
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

    async with session_scope() as session:
        async with session.begin():
            locked_user = await _oauth_repository.lock_user(session, user_id)
            if locked_user is None or not bool(locked_user.is_verified):
                raise ValueError("Only verified users can issue connector credentials.")
            active = await _oauth_repository.count_active_user_clients(session, user_id)
            if active >= MAX_CLIENTS_PER_USER:
                raise ClientLimitReachedError(
                    f"You can keep at most {MAX_CLIENTS_PER_USER} credentials."
                )
            await _oauth_repository.insert_personal_client(
                session,
                client_id=client_id,
                metadata=_serialize_client(client),
                encrypted_secret=encrypted_secret,
                user_id=user_id,
                provider=MANUAL_CLIENT_PROVIDER,
                label=cleaned_label,
            )

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "label": cleaned_label or "",
        "redirect_uri": registered_redirect_uri,
        "token_endpoint_auth_method": "client_secret_post" if client_secret else "none",
        "mcp_server_url": get_mcp_server_url(),
        "scopes": client_scopes,
    }


async def list_user_clients(user_id: int) -> dict[str, Any]:
    """List the user's saved connector credentials without ever exposing secrets."""
    async with session_scope() as session:
        rows = await _oauth_repository.list_user_clients(session, user_id)
        clients = []
        for user_client, client in rows:
            redirect_uris = client.client_metadata.get("redirect_uris") or []
            redirect_uri = str(redirect_uris[0]) if redirect_uris else ""
            clients.append(
                {
                    "client_id": str(user_client.client_id),
                    "label": user_client.label or "",
                    "redirect_uri": redirect_uri,
                    "token_endpoint_auth_method": str(
                        client.client_metadata.get(
                            "token_endpoint_auth_method", "client_secret_post"
                        )
                    ),
                    "created_at": user_client.created_at.isoformat(),
                }
            )
        return {
            "clients": clients,
            "default_redirect_uri": DEFAULT_MCP_OAUTH_REDIRECT_URI,
            "mcp_server_url": get_mcp_server_url(),
        }


async def update_user_client_label(user_id: int, client_id: str, label: str) -> bool:
    """Update a personal credential's display label without rotating its secret."""
    cleaned_label = _clean_user_label(label)
    async with session_scope() as session:
        async with session.begin():
            return await _oauth_repository.update_user_client_label(
                session, user_id, client_id, cleaned_label
            )


async def revoke_user_client(user_id: int, client_id: str) -> bool:
    """Delete a saved credential and sever every connection made with it.

    認証情報を削除したら、その認証情報で確立済みの接続（grant とトークン）も同時に
    失効させ、外部サービス側の接続がすぐに切れるようにする。

    Revoking a credential also revokes the grants and tokens created with it, so
    the external connection stops working immediately.
    """
    async with session_scope() as session:
        async with session.begin():
            return await _oauth_repository.revoke_user_client(session, user_id, client_id)


async def _create_authorization_code(user_id: int, request_data: dict[str, Any]) -> str:
    raw_code = secrets.token_urlsafe(32)
    client = _parse_client(request_data["client"])
    params = request_data["params"]
    grant_id = uuid4()
    now = _utc_now()
    client_host = _display_client_host(client, params["redirect_uri"])
    async with session_scope() as session:
        async with session.begin():
            await _oauth_repository.create_grant_and_code(
                session,
                grant_id=grant_id,
                user_id=user_id,
                client_id=str(client.client_id),
                client_name=client.client_name or str(client.client_id),
                client_host=client_host,
                scopes=params["scopes"],
                scope_version=MCP_OAUTH_SCOPE_VERSION,
                code_digest=_digest(raw_code),
                redirect_uri=params["redirect_uri"],
                code_challenge=params["code_challenge"],
                resource=params["resource"],
                expires_at=now + timedelta(seconds=AUTHORIZATION_CODE_TTL_SECONDS),
            )
    return raw_code


async def _user_is_verified(user_id: int) -> bool:
    async with session_scope() as session:
        return await _oauth_repository.is_user_verified(session, user_id)


async def _issue_tokens(grant_id: UUID, client_id: str, scopes: list[str], resource: str) -> OAuthToken:
    access_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(32)
    now = _utc_now()
    async with session_scope() as session:
        async with session.begin():
            await _oauth_repository.insert_tokens(
                session,
                grant_id=grant_id,
                client_id=client_id,
                scopes=scopes,
                resource=resource,
                access_token_digest=_digest(access_token),
                access_expires_at=now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
                refresh_token_digest=_digest(refresh_token),
                refresh_expires_at=now + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS),
            )
    return OAuthToken(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_TTL_SECONDS,
        scope=" ".join(scopes),
    )


async def _revoke_grant_family(session: Any, grant_id: UUID) -> None:
    """Revoke a grant and every token issued under it."""
    await _oauth_repository.revoke_grant_family(session, grant_id)


async def _revoke_if_legacy_scope_grant(
    session: Any, grant_id: UUID, scope_version: int
) -> bool:
    """Expire pre-fix grants lazily after blue/green traffic reaches the new app."""
    if scope_version >= MCP_OAUTH_SCOPE_VERSION:
        return False
    await _revoke_grant_family(session, grant_id)
    return True


async def _load_code(client_id: str, raw_code: str) -> StoredAuthorizationCode | None:
    async with session_scope() as session:
        async with session.begin():
            record = await _oauth_repository.load_authorization_code(
                session, client_id, _digest(raw_code)
            )
            if record is None:
                return None
            if await _revoke_if_legacy_scope_grant(
                session, record.code.grant_id, record.scope_version
            ):
                return None
            return StoredAuthorizationCode(
                code=raw_code,
                client_id=client_id,
                scopes=list(record.code.scopes),
                expires_at=record.code.expires_at.timestamp(),
                redirect_uri=record.code.redirect_uri,
                redirect_uri_provided_explicitly=True,
                code_challenge=record.code.code_challenge,
                resource=record.code.resource,
                subject=str(record.user_id),
                grant_id=record.code.grant_id,
            )


async def _consume_code_and_issue(code: StoredAuthorizationCode) -> OAuthToken:
    access_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(32)
    now = _utc_now()
    async with session_scope() as session:
        async with session.begin():
            consumed = await _oauth_repository.consume_authorization_code(
                session, _digest(code.code)
            )
            if not consumed:
                raise TokenError("invalid_grant", "Authorization code was already used.")
            await _oauth_repository.insert_tokens(
                session,
                grant_id=code.grant_id,
                client_id=code.client_id,
                scopes=code.scopes,
                resource=code.resource or get_mcp_server_url(),
                access_token_digest=_digest(access_token),
                access_expires_at=now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
                refresh_token_digest=_digest(refresh_token),
                refresh_expires_at=now + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS),
            )
    return OAuthToken(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_TTL_SECONDS,
        scope=" ".join(code.scopes),
    )


async def _load_refresh(client_id: str, raw_token: str) -> StoredRefreshToken | None:
    async with session_scope() as session:
        async with session.begin():
            record = await _oauth_repository.load_refresh_token(
                session, client_id, _digest(raw_token)
            )
            if record is None:
                return None
            if await _revoke_if_legacy_scope_grant(
                session, record.token.grant_id, record.scope_version
            ):
                return None
            replaced_at = record.token.replaced_at
            if replaced_at is not None and replaced_at <= _utc_now() - timedelta(
                seconds=REFRESH_TOKEN_ROTATION_GRACE_SECONDS
            ):
                await _revoke_grant_family(session, record.token.grant_id)
                return None
            return StoredRefreshToken(
                token=raw_token,
                client_id=client_id,
                scopes=list(record.token.scopes),
                expires_at=int(record.token.expires_at.timestamp()),
                subject=str(record.user_id),
                grant_id=record.token.grant_id,
                resource=record.token.resource,
            )


async def _refresh_access_token(refresh: StoredRefreshToken, scopes: list[str]) -> OAuthToken:
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
    try:
        requested_scopes = _normalize_scopes(scopes, default=tuple(refresh.scopes))
    except ValueError as exc:
        raise TokenError("invalid_scope", "Requested OAuth scopes are not supported.") from exc
    if not set(requested_scopes).issubset(set(refresh.scopes)):
        raise TokenError(
            "invalid_scope",
            "Refresh tokens cannot be exchanged for broader OAuth scopes.",
        )

    new_refresh_token = secrets.token_urlsafe(32)
    access_token = secrets.token_urlsafe(32)
    now = _utc_now()
    async with session_scope() as session:
        async with session.begin():
            record = await _oauth_repository.load_refresh_token(
                session,
                refresh.client_id,
                _digest(refresh.token),
                for_update=True,
            )
            if record is None:
                raise TokenError("invalid_grant", "Refresh token is no longer valid.")
            if await _revoke_if_legacy_scope_grant(
                session, record.token.grant_id, record.scope_version
            ):
                raise TokenError("invalid_grant", "Refresh token requires reauthorization.")
            replaced_at = record.token.replaced_at
            if replaced_at is not None and replaced_at <= _utc_now() - timedelta(
                seconds=REFRESH_TOKEN_ROTATION_GRACE_SECONDS
            ):
                await _revoke_grant_family(session, record.token.grant_id)
                raise TokenError("invalid_grant", "Refresh token reuse was detected.")
            if not await _oauth_repository.mark_refresh_rotated(
                session, _digest(refresh.token), now
            ):
                raise TokenError("invalid_grant", "Refresh token is no longer valid.")
            await _oauth_repository.insert_tokens(
                session,
                grant_id=record.token.grant_id,
                client_id=refresh.client_id,
                scopes=requested_scopes,
                resource=record.token.resource,
                access_token_digest=_digest(access_token),
                access_expires_at=now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
                refresh_token_digest=_digest(new_refresh_token),
                refresh_expires_at=now + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS),
            )
    return OAuthToken(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=ACCESS_TOKEN_TTL_SECONDS,
        scope=" ".join(requested_scopes),
    )


async def _load_access(raw_token: str) -> AccessToken | None:
    async with session_scope() as session:
        async with session.begin():
            record = await _oauth_repository.load_access_token(session, _digest(raw_token))
            if record is None or record.token.resource != get_mcp_server_url():
                return None
            if await _revoke_if_legacy_scope_grant(
                session, record.grant_id, record.scope_version
            ):
                return None
            await _oauth_repository.touch_access_token(
                session, _digest(raw_token), record.grant_id
            )
            return AccessToken(
                token=raw_token,
                client_id=record.token.client_id,
                scopes=list(record.token.scopes),
                expires_at=int(record.token.expires_at.timestamp()),
                resource=record.token.resource,
                subject=str(record.user_id),
            )


class ChatCoreOAuthProvider(OAuthAuthorizationServerProvider[StoredAuthorizationCode, StoredRefreshToken, AccessToken]):
    """Official MCP SDK provider backed by Chat-Core's PostgreSQL database."""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        client = await _load_registered_client(client_id)
        if client is not None:
            return client
        return await _load_cimd_client(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        method = client_info.token_endpoint_auth_method or "client_secret_post"
        if method not in {"none", "client_secret_post", "client_secret_basic"}:
            raise RegistrationError("invalid_client_metadata", "Unsupported token endpoint auth method.")
        try:
            client_info.scope = _normalize_client_scope(client_info.scope)
        except ValueError as exc:
            raise RegistrationError(
                "invalid_client_metadata",
                "Requested OAuth scopes are not supported.",
            ) from exc
        await _store_client(client_info)

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        try:
            registered_scopes = _normalize_client_scope(client.scope).split()
        except ValueError as exc:
            raise AuthorizeError("invalid_scope", "The OAuth client has invalid registered scopes.") from exc
        try:
            # Some MCP clients, including clients that rely entirely on
            # protected-resource discovery, omit ``scope`` from /authorize.
            # In that case authorize the client's registered scope set rather
            # than falling back to the server's former prompts:write-only era.
            scopes = _normalize_scopes(params.scopes, default=tuple(registered_scopes))
        except ValueError as exc:
            raise AuthorizeError("invalid_scope", "One or more requested OAuth scopes are not available.") from exc
        if not set(scopes).issubset(set(registered_scopes)):
            raise AuthorizeError("invalid_scope", "The OAuth client was not registered for every requested scope.")
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
        return await _load_code(str(client.client_id), authorization_code)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: StoredAuthorizationCode) -> OAuthToken:
        return await _consume_code_and_issue(authorization_code)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> StoredRefreshToken | None:
        return await _load_refresh(str(client.client_id), refresh_token)

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: StoredRefreshToken, scopes: list[str]) -> OAuthToken:
        return await _refresh_access_token(refresh_token, scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        return await _load_access(token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await revoke_token_value(token.token)


def read_consent_request(token: str) -> dict[str, Any] | None:
    try:
        return _consent_serializer().loads(token, max_age=CONSENT_REQUEST_TTL_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def consent_details(token: str) -> dict[str, Any] | None:
    request_data = read_consent_request(token)
    if not request_data:
        return None
    try:
        scopes = _normalize_scopes(request_data.get("params", {}).get("scopes"))
    except (TypeError, ValueError):
        return None
    client = _parse_client(request_data["client"])
    redirect_host = urlparse(request_data["params"]["redirect_uri"]).hostname or ""
    return {
        "client_name": client.client_name or str(client.client_id),
        "client_id": str(client.client_id),
        "client_host": _display_client_host(client, request_data["params"]["redirect_uri"]),
        "redirect_host": redirect_host,
        # ``scope`` remains the OAuth-standard, space-delimited compatibility
        # field. The structured fields let browser clients present each grant
        # separately without parsing or inventing labels.
        "scope": " ".join(scopes),
        "scopes": scopes,
        "scope_labels": {scope: MCP_SCOPE_LABELS[scope] for scope in scopes},
        "localhost_warning": redirect_host.lower() in {"localhost", "127.0.0.1", "::1"},
    }


async def complete_consent(token: str, user_id: int, approved: bool) -> str | None:
    request_data = read_consent_request(token)
    if not request_data or not await _user_is_verified(user_id):
        return None
    try:
        request_data["params"]["scopes"] = _normalize_scopes(
            request_data.get("params", {}).get("scopes")
        )
    except (KeyError, TypeError, ValueError):
        return None
    client_id = request_data.get("client", {}).get("client_id")
    if not isinstance(client_id, str) or not await _user_client_is_authorized_for_user(client_id, user_id):
        logger.warning("Rejected MCP OAuth consent for a client not owned by user %s.", user_id)
        return None
    params = request_data["params"]
    if not approved:
        return construct_redirect_uri(params["redirect_uri"], error="access_denied", state=params.get("state"))
    code = await _create_authorization_code(user_id, request_data)
    return construct_redirect_uri(params["redirect_uri"], code=code, state=params.get("state"))


async def list_connections(user_id: int) -> list[dict[str, Any]]:
    async with session_scope() as session:
        rows = await _oauth_repository.list_connections(
            session, user_id, MCP_OAUTH_SCOPE_VERSION
        )
        return [
            {
                "id": str(row.id),
                "client_name": row.client_name,
                "client_host": row.client_host,
                "display_name": row.display_name,
                "scopes": list(row.scopes or []),
                "created_at": row.created_at.isoformat(),
                "last_used_at": row.last_used_at.isoformat()
                if row.last_used_at
                else None,
            }
            for row in rows
        ]


async def revoke_connection(user_id: int, grant_id: str) -> bool:
    try:
        parsed_grant_id = UUID(grant_id)
    except (TypeError, ValueError):
        return False
    async with session_scope() as session:
        async with session.begin():
            return await _oauth_repository.revoke_connection(
                session, user_id, parsed_grant_id
            )


async def update_connection_display_name(user_id: int, grant_id: str, display_name: str) -> bool:
    """Set a user-facing alias while retaining the OAuth client's original name."""
    cleaned_name = _clean_user_label(display_name)
    try:
        parsed_grant_id = UUID(grant_id)
    except (TypeError, ValueError):
        return False
    async with session_scope() as session:
        async with session.begin():
            return await _oauth_repository.update_connection_display_name(
                session, user_id, parsed_grant_id, cleaned_name
            )


async def revoke_token_value(raw_token: str) -> None:
    async with session_scope() as session:
        async with session.begin():
            await _oauth_repository.revoke_token_value(session, _digest(raw_token))
