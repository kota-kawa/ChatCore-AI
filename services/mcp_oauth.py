"""Chat-Core のリモート MCP エンドポイントが使う OAuth 認可サーバーの実装と永続化。

クライアント登録（DCR・CIMD・個人用の手動発行）、同意画面のための署名付きリクエスト、認可コードとアクセス/リフレッシュトークンの
発行・回転・失効を扱う。DB 操作は `McpOAuthRepository` に委ね、`mcp_server.py` が MCP SDK の認可プロバイダとして使う。
OAuth authorization server implementation and persistence behind Chat-Core's remote MCP endpoint.
Covers client registration (DCR, CIMD and manually issued personal clients), the signed request behind the consent screen,
and issuing, rotating and revoking authorization codes and access/refresh tokens.
Database work is delegated to `McpOAuthRepository`; `mcp_server.py` uses this as the MCP SDK's authorization provider.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

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
)
from mcp.shared.auth import (
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
from services.repositories.mcp_oauth_repository import (
    CIMD_REGISTRATION_METHOD,
    DCR_REGISTRATION_METHOD,
    McpOAuthRepository,
)
from services.runtime_config import get_session_secret_key
from services.url_fetcher import (
    _new_direct_session,
    _pin_dns,
    _resolve_safe_ip,
    canonicalize_url,
    url_for_logging,
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
# 新規登録のクライアントは、サーバーが対応する任意の scope の組み合わせを要求できる必要がある。
# 認可リクエストが ``scope`` を省略した場合は、そのクライアントに登録された scope を使う。既存の許可は保存済みの scope のままなので、
# サーバーの対応 scope が増えても、それだけで権限が広がることはない。
# Newly registered clients need to be able to request any supported subset.
# Authorization requests that omit ``scope`` use the scopes registered for
# that client. Existing grants keep their persisted scopes and therefore never
# gain access merely because the server's supported scope set grows.
MCP_DEFAULT_SCOPES = MCP_ALLOWED_SCOPES
# scope の体系の版。これより古い版で発行された許可は、遅延的に失効させて再同意を求める（_revoke_if_legacy_scope_grant）。
# Version of the scope scheme; grants issued under an older version are revoked lazily to force re-consent.
MCP_OAUTH_SCOPE_VERSION = 2
# 同意画面に出す、scope ごとの利用者向け説明文。
# User-facing description of each scope shown on the consent screen.
MCP_SCOPE_LABELS = {
    MCP_PROMPTS_READ_SCOPE: "公開プロンプトとSKILLを検索・閲覧する",
    MCP_PROMPTS_WRITE_SCOPE: "公開プロンプトを投稿する",
    MCP_MEMOS_READ_SCOPE: "保存したメモを検索・閲覧する",
    MCP_MEMOS_WRITE_SCOPE: "保存したメモを編集する",
    MCP_CONTEXT_READ_SCOPE: "パーソナル・コンテキストを読み取る",
    MCP_CONTEXT_WRITE_SCOPE: "パーソナル・コンテキストを保存・編集する",
}
# 個人用に手動発行したクライアントの提供元を表す値。
# Provider value marking a manually issued personal client.
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
# CIMD（クライアント ID メタデータ文書）の取得に関する上限。取得結果と失敗（ネガティブ）結果をそれぞれ別の時間だけキャッシュする。
# Limits for fetching CIMD (Client ID Metadata Documents); successes and failures are cached for different durations.
MAX_CIMD_BYTES = 64 * 1024
MAX_CIMD_CACHE_SECONDS = 3600
NEGATIVE_CIMD_CACHE_SECONDS = 300
MAX_USER_LABEL_LENGTH = 100
MAX_CLIENTS_PER_USER = 20
MAX_REDIRECT_URI_LENGTH = 2048

# CIMD のキャッシュ(LRU)と、取得用スレッドプール・同時取得数の制限。いずれも初回利用時に作る。
# CIMD cache (LRU) plus the fetch thread pool and its concurrency limiter, created on first use.
_cimd_cache: OrderedDict[str, tuple[float, OAuthClientInformationFull | None]] = OrderedDict()
_cimd_cache_lock = threading.Lock()
_cimd_executor_lock = threading.Lock()
_cimd_executor: ThreadPoolExecutor | None = None
_cimd_fetch_slots: threading.BoundedSemaphore | None = None
logger = logging.getLogger(__name__)
_oauth_repository = McpOAuthRepository()


# 個人用クライアントの発行上限に達したときの例外。
# Raised when the personal-client issuance cap is reached.
class ClientLimitReachedError(Exception):
    # 接続資格情報の保有数が上限に達したことを示す。
    """Raised when a user already holds the maximum number of connector credentials."""


# 個人用クライアント作成時のコールバック URL が不正なときの例外。
# Raised when a callback URL for a personal client is invalid.
class InvalidRedirectUriError(ValueError):
    # 利用者が指定したOAuthリダイレクトURIが不正または危険であることを示す。
    """Raised when a user-supplied OAuth redirect URI is unsafe or malformed."""


def _loopback_redirect_uris_match(registered: str, requested: str) -> bool:
    """ネイティブクライアントのループバックのコールバックを、一時的なポートを無視して照合する。

    Match native-client loopback callbacks while ignoring the ephemeral port.
    """
    try:
        registered_url = urlparse(registered)
        requested_url = urlparse(requested)
        # RFC 8252 のループバック比較ではポート値自体は使わないが、`.port` の評価が不正な
        # ポート表記の検証になるため、ここで明示的に読み出して不正URIを弾く。
        # The RFC 8252 loopback comparison ignores the port value itself, but evaluating
        # `.port` validates the port syntax, so read both here to reject malformed URIs.
        _ = (registered_url.port, requested_url.port)
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


# CIMD クライアントの情報。通常の照合に失敗したときだけ、RFC 8252 のループバック(ポート違いを許容)で照合し直す。
# CIMD client information; only when the normal check fails, fall back to the RFC 8252 loopback match (any port).
class CimdOAuthClientInformation(OAuthClientInformationFull):
    # RFC 8252のループバック互換性を持つCIMDクライアント情報。
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


# DB に保存した認可コード。どの許可(grant)に属するかを持つ。
# An authorization code loaded from the database, tagged with the grant it belongs to.
class StoredAuthorizationCode(AuthorizationCode):
    grant_id: UUID


# DB に保存したリフレッシュトークン。属する許可(grant)と対象リソースを持つ。
# A refresh token loaded from the database, tagged with its grant and target resource.
class StoredRefreshToken(RefreshToken):
    grant_id: UUID
    resource: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _digest(value: str) -> str:
    # コードやトークンは平文を保存せず、このダイジェストで DB と照合する。
    # Codes and tokens are never stored in plaintext; they are matched in the database by this digest.
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _serialize_client(client: OAuthClientInformationFull) -> dict[str, Any]:
    # クライアント情報を JSON 化する。シークレットは含めず、別に暗号化して保存する。
    # Serialize client info to JSON without the secret, which is stored separately in encrypted form.
    return client.model_dump(mode="json", exclude={"client_secret"})


def _normalize_scopes(
    scopes: list[str] | tuple[str, ...] | None,
    *,
    default: tuple[str, ...] = MCP_DEFAULT_SCOPES,
) -> list[str]:
    """OAuth の scope が対応範囲の部分集合かを検証する。要求された順序は保つ。

    Validate an OAuth scope subset while preserving the requested order.
    """
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
    # クライアントの scope 文字列(空白区切り)を検証・正規化し、未指定なら既定の scope にする。
    # Validate and normalize the client's space-delimited scope string, using the default when unset.
    requested = scope.split() if isinstance(scope, str) and scope.strip() else list(default)
    return " ".join(_normalize_scopes(requested, default=default))


def _parse_client(value: Any, secret: str | None = None) -> OAuthClientInformationFull:
    # 保存した JSON(文字列または辞書)から、シークレットを戻したクライアント情報を復元する。
    # Rebuild client info from stored JSON (string or dict), putting the secret back.
    raw = json.loads(value) if isinstance(value, str) else dict(value)
    raw["client_secret"] = secret
    return OAuthClientInformationFull.model_validate(raw)


def _display_client_host(client: OAuthClientInformationFull, redirect_uri: str) -> str:
    """OAuth クライアントが意味を持たない client ID を使っていても、表示用のホスト名を求める。

    Resolve a display host even when an OAuth client uses an opaque client ID.
    """
    for candidate in (client.client_uri, client.client_id, redirect_uri):
        hostname = urlparse(str(candidate or "")).hostname
        if hostname:
            return hostname
    return "unknown"


def _fernet() -> MultiFernet:
    # クライアントシークレットの暗号化・復号に使う。複数の鍵を持てるので、鍵を入れ替えても古い値を復号できる。
    # Used to encrypt and decrypt client secrets; holding several keys lets old values decrypt after a key rotation.
    return MultiFernet([Fernet(key.encode("ascii")) for key in get_mcp_encryption_keys()])


def _consent_serializer() -> URLSafeTimedSerializer:
    # 同意画面へ渡す認可リクエストの署名付きトークン用。改ざんを防ぎ、有効期限つきで読み出せる。
    # Signed token for the authorization request handed to the consent screen; tamper-proof and readable with an expiry.
    secret = get_session_secret_key()
    if not secret:
        raise RuntimeError("FASTAPI_SECRET_KEY is required for MCP OAuth.")
    return URLSafeTimedSerializer(secret, salt="chat-core.mcp-oauth-consent")


def _resource_matches_server(requested: str | None) -> bool:
    """RFC 8707 の resource 指示子が、この MCP サーバーを指しているか確認する。

    Check an RFC 8707 resource indicator against this MCP server.

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
    # リダイレクト URI は HTTPS のみ許可し、HTTP はループバック(ローカルのネイティブクライアント)に限る。
    # 認証情報やフラグメントを含むもの、不正なポートは拒否する。
    # Allow only HTTPS redirect URIs, with HTTP limited to loopback (local native clients);
    # reject credentials, fragments and invalid ports.
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
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise RegistrationError("invalid_redirect_uri", "Redirect URI is invalid.")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
        raise RegistrationError(
            "invalid_redirect_uri",
            "Redirect URI must use HTTPS, except for loopback HTTP callbacks.",
        )


def _validate_redirect_uris(client: OAuthClientInformationFull) -> None:
    # クライアントが登録したリダイレクト URI をすべて検証する。
    # Validate every redirect URI the client registered.
    for redirect_uri in client.redirect_uris or []:
        _validate_redirect_uri(str(redirect_uri))


def _clean_redirect_uri(redirect_uri: str | None) -> str:
    """個人用 OAuth クライアントの作成時に渡されたコールバック URL を1件検証する。

    Validate one callback URL supplied when creating a personal OAuth client.
    """
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
    # CIMD 取得用のスレッドプールと同時実行数の制限を、初回に一度だけ作って返す。
    # Create the CIMD fetch thread pool and concurrency limiter once, on first use.
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
    # 期限切れを掃除してから参照する。戻り値は (見つかったか, 値)。値が None の「見つかった」は失敗の記録(ネガティブキャッシュ)。
    # 参照したエントリは末尾へ移して、LRU の追い出し順を更新する。
    # Drop expired entries, then look up: returns (found, value). A found None is a recorded failure (negative cache).
    # A hit is moved to the end to refresh its LRU position.
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
    # 上限件数を超えたら、最も古く使われたエントリから追い出す。
    # Evict the least recently used entries once the size cap is exceeded.
    expires_at = _utc_now().timestamp() + ttl_seconds
    max_entries = get_mcp_cimd_cache_entries()
    with _cimd_cache_lock:
        _cimd_cache.pop(client_id, None)
        _cimd_cache[client_id] = (expires_at, client)
        while len(_cimd_cache) > max_entries:
            _cimd_cache.popitem(last=False)


def _cimd_client(client_id: str) -> OAuthClientInformationFull | None:
    # CIMD では client_id そのものが HTTPS の URL で、その先のメタデータ文書をクライアント情報として使う。
    # 外部 URL を取り込むため、安全な IP への解決(DNS 固定)、リダイレクト禁止、サイズ上限、JSON 型の確認を行い、
    # client_id の一致と公開クライアント(認証なし)であることも確かめる。失敗は短時間キャッシュして再取得を抑える。
    # With CIMD the client_id itself is an HTTPS URL whose metadata document serves as the client info.
    # Because it fetches an external URL, it resolves to a safe IP (DNS pinned), forbids redirects, caps the size and checks for JSON,
    # then confirms the client_id matches and the client is public (no authentication). Failures are cached briefly.
    now = _utc_now().timestamp()
    found, cached = _read_cimd_cache(client_id, now)
    if found:
        return cached

    original = urlparse(client_id)
    if original.scheme != "https" or not original.netloc or not original.path:
        return None
    normalized_url = canonicalize_url(client_id)
    if normalized_url is None:
        return None
    parsed = urlparse(normalized_url)
    ip = _resolve_safe_ip(normalized_url)
    if ip is None or not parsed.hostname:
        return None
    try:
        with _new_direct_session() as session, _pin_dns({parsed.hostname: ip}):
            response = session.get(
                normalized_url,
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
        # CIMD のメタデータはクライアント全体に共通で、通常はこのサーバー固有の scope を書けない。
        # 許可する scope は認可サーバー側が持つため、provider が authorize() で厳密な scope 検査を行う前に、
        # SDK のクライアント側検証でも使えるよう設定しておく。
        # CIMD metadata is client-global and normally cannot name this server's
        # private scopes. The authorization server owns the allowed scope set;
        # make it available to the SDK's client-level validation before the
        # provider applies its own strict scope check in authorize().
        client.scope = " ".join(MCP_ALLOWED_SCOPES)
        _validate_redirect_uris(client)
        _write_cimd_cache(client_id, client, MAX_CIMD_CACHE_SECONDS)
    except Exception:
        # 例外の詳細に署名付きのクライアント URL が含まれうるため、ログには整形した URL だけを出す。
        # Exception details may contain the original signed client URL.
        logger.warning("Failed to load CIMD metadata for client %s; caching a negative result.", url_for_logging(client_id))
        _write_cimd_cache(client_id, None, NEGATIVE_CIMD_CACHE_SECONDS)
        return None
    else:
        return client


async def _load_cimd_client(client_id: str) -> OAuthClientInformationFull | None:
    # ブロッキングの取得を別スレッドで実行する。同時実行数の枠が埋まっていれば待たずに拒否し、認可エンドポイントが詰まるのを防ぐ。
    # Run the blocking fetch in a worker thread; if the concurrency slots are full, reject at once instead of queueing,
    # so the authorization endpoints cannot be clogged.
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
    # DB に登録済み(DCR または個人用)のクライアントを読み、暗号化されたシークレットを復号して返す。
    # Load a registered (DCR or personal) client from the database, decrypting its stored secret.
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
        # 物理列metadataに対応するORM属性はclient_metadata。Base.metadataを参照しない。
        # ``client_metadata`` is the ORM attribute for the physical JSONB
        # column named ``metadata``.  Do not access Base.metadata here.
        return _parse_client(row.client_metadata, secret)


async def _store_client(client: OAuthClientInformationFull) -> None:
    # DCR で登録されたクライアントを保存する。リダイレクト URI と scope を検証し、シークレットは暗号化して保存する。
    # Store a client registered through DCR: validate redirect URIs and scopes, and encrypt the secret.
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
    async with session_scope() as session, session.begin():
        await _oauth_repository.store_client(
            session,
            client_id=str(client.client_id),
            metadata=_serialize_client(client),
            encrypted_secret=encrypted,
            registration_method=DCR_REGISTRATION_METHOD,
        )


async def _store_cimd_client(client: OAuthClientInformationFull) -> None:
    """Record a CIMD client so its grants and tokens have a foreign-key parent.

    DCR クライアントは登録時に、個人用クライアントは発行時に ``mcp_oauth_clients`` へ
    保存されるが、CIMD クライアントはメタデータ文書を読むだけで保存されていなかった。
    ``mcp_oauth_grants`` / ``mcp_oauth_tokens`` の ``client_id`` が同表を参照するように
    なったため、行が無いままでは同意の確定もトークン更新も外部キー違反（＝同意画面の
    「内部エラーが発生しました。」）で失敗する。ここで一度だけ親行を作れば、既存の接続も
    次回のトークン更新で追いつく。保存済みのクライアントに対しては何もしない INSERT。

    A DCR client is stored when it registers and a personal client when it is issued, but a
    CIMD client used to be read from its metadata document and never persisted. Now that
    ``mcp_oauth_grants`` and ``mcp_oauth_tokens`` reference ``mcp_oauth_clients`` by
    ``client_id``, a missing row makes both consent completion and token refresh fail with a
    foreign-key violation. Creating the parent row here also lets connections established
    before the constraint recover on their next token request. The insert does nothing when
    the client is already stored.
    """
    async with session_scope() as session, session.begin():
        await _oauth_repository.store_client(
            session,
            client_id=str(client.client_id),
            metadata=_serialize_client(client),
            # CIMD クライアントは常に public で、シークレットを持たない。
            # A CIMD client is always public and therefore has no secret.
            encrypted_secret=None,
            registration_method=CIMD_REGISTRATION_METHOD,
        )


async def _user_client_is_authorized_for_user(client_id: str, user_id: int) -> bool:
    """汎用のクライアントは全ユーザーに許可し、個人用クライアントは所有者だけに許可する。

    Allow generic clients for every user and personal clients only for their owner.
    """
    async with session_scope() as session:
        return await _oauth_repository.user_client_is_authorized(session, client_id, user_id)


def _clean_user_label(label: str | None) -> str | None:
    """利用者が管理するラベルを正規化する。空や不正ならラベルなしにする。

    Normalize a user-managed label, or fall back to no label.
    """
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

    async with session_scope() as session, session.begin():
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
    """利用者が保存したコネクター認証情報を、シークレットを一切出さずに一覧にする。

    List the user's saved connector credentials without ever exposing secrets.
    """
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
    """個人用認証情報の表示ラベルを、シークレットを変えずに更新する。

    Update a personal credential's display label without rotating its secret.
    """
    cleaned_label = _clean_user_label(label)
    async with session_scope() as session, session.begin():
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
    async with session_scope() as session, session.begin():
        return await _oauth_repository.revoke_user_client(session, user_id, client_id)


async def _create_authorization_code(user_id: int, request_data: dict[str, Any]) -> str:
    # 同意が承認されたときに、許可(grant)と認可コードを作る。DB にはコードのダイジェストだけを保存し、平文は呼び出し元へ返す。
    # On approval, create the grant and authorization code. Only the code's digest is stored; the plaintext goes back to the caller.
    raw_code = secrets.token_urlsafe(32)
    client = _parse_client(request_data["client"])
    params = request_data["params"]
    grant_id = uuid4()
    now = _utc_now()
    client_host = _display_client_host(client, params["redirect_uri"])
    async with session_scope() as session, session.begin():
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
    # メール認証済みのユーザーだけがコネクターの認証情報の発行や同意をできるため、その確認に使う。
    # Only email-verified users may issue connector credentials or consent, and this checks that.
    async with session_scope() as session:
        return await _oauth_repository.is_user_verified(session, user_id)


async def _revoke_grant_family(session: Any, grant_id: UUID) -> None:
    """許可(grant)と、それに紐づいて発行されたすべてのトークンを失効させる。

    Revoke a grant and every token issued under it.
    """
    await _oauth_repository.revoke_grant_family(session, grant_id)


async def _revoke_if_legacy_scope_grant(
    session: Any, grant_id: UUID, scope_version: int
) -> bool:
    """修正前に発行された許可を、ブルー/グリーンの切り替えで新アプリにトラフィックが届いた後に、遅延的に失効させる。

    Expire pre-fix grants lazily after blue/green traffic reaches the new app.
    """
    if scope_version >= MCP_OAUTH_SCOPE_VERSION:
        return False
    await _revoke_grant_family(session, grant_id)
    return True


async def _load_code(client_id: str, raw_code: str) -> StoredAuthorizationCode | None:
    # 認可コードを読み込む。旧 scope 版の許可に属するコードは失効させて None を返す。
    # Load an authorization code; a code belonging to a legacy-scope grant is revoked and yields None.
    async with session_scope() as session, session.begin():
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
    # 認可コードを使用済みにしてトークンを発行する。同じトランザクションで消費するため、二重に使うと invalid_grant になる。
    # Mark the code used and issue tokens in one transaction, so reusing a code fails with invalid_grant.
    access_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(32)
    now = _utc_now()
    async with session_scope() as session, session.begin():
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
    # リフレッシュトークンを読み込む。旧 scope 版の許可、または回転後に猶予期間を過ぎたトークン(再利用の疑い)は、
    # 許可ごと失効させて None を返す。
    # Load a refresh token. A legacy-scope grant, or a token reused after its rotation grace window (suspected theft),
    # revokes the whole grant and yields None.
    async with session_scope() as session, session.begin():
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
    """リフレッシュトークンを回転させて新しいアクセストークンを発行する。再利用には猶予期間がある。

    Rotate the refresh token and issue a fresh access token, with a reuse grace window.

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
    async with session_scope() as session, session.begin():
        # 並行するリフレッシュが同じトークンを同時に回転しないよう、行をロックして読み直す。
        # Re-read with a row lock so concurrent refreshes cannot rotate the same token at once.
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
    # アクセストークンを検証して返す。この MCP サーバー宛て(resource)のものだけを有効とし、使用時刻を更新する。
    # Validate an access token: only tokens issued for this MCP server's resource are valid, and last-use time is updated.
    async with session_scope() as session, session.begin():
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


# MCP SDK の認可プロバイダ実装。Chat-Core の PostgreSQL をバックエンドに、クライアント解決・認可・トークン交換・失効を行う。
# MCP SDK authorization provider backed by Chat-Core's PostgreSQL: client lookup, authorization, token exchange and revocation.
class ChatCoreOAuthProvider(OAuthAuthorizationServerProvider[StoredAuthorizationCode, StoredRefreshToken, AccessToken]):
    # Chat-CoreのPostgreSQLを使う公式MCP SDKのプロバイダー実装。
    """Official MCP SDK provider backed by Chat-Core's PostgreSQL database."""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        # まず DB の登録済みクライアントを探し、無ければ client_id を URL とみなして CIMD として解決する。
        # Look up a registered client first; otherwise treat the client_id as a URL and resolve it as CIMD.
        client = await _load_registered_client(client_id)
        if client is not None:
            return client
        cimd_client = await _load_cimd_client(client_id)
        if cimd_client is None:
            return None
        # /authorize も /token も必ずこの経路を通るため、ここで親行を用意しておけば
        # 認可コードの発行とトークン更新の両方が外部キーを満たせる。
        # Both /authorize and /token resolve their client here, so filling the parent row
        # at this point covers authorization-code creation and token refresh alike.
        await _store_cimd_client(cimd_client)
        return cimd_client

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
        # 要求の scope と resource を検証し、問題なければ署名付きの要求を同意画面(/oauth/authorize)へ渡す URL を返す。
        # 認可コードはここでは発行せず、利用者が同意した時点(complete_consent)で発行する。
        # Validate the requested scopes and resource, then return the URL that hands a signed request to the consent screen
        # (/oauth/authorize). No code is issued here; it is issued when the user consents (complete_consent).
        try:
            registered_scopes = _normalize_client_scope(client.scope).split()
        except ValueError as exc:
            raise AuthorizeError("invalid_scope", "The OAuth client has invalid registered scopes.") from exc
        try:
            # scopeを省くクライアントには、旧来の単一権限へ戻さず登録済みの権限集合を使う。
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

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: StoredAuthorizationCode,
    ) -> OAuthToken:
        return await _consume_code_and_issue(authorization_code)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> StoredRefreshToken | None:
        return await _load_refresh(str(client.client_id), refresh_token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: StoredRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        return await _refresh_access_token(refresh_token, scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        return await _load_access(token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await revoke_token_value(token.token)


def read_consent_request(token: str) -> dict[str, Any] | None:
    # 同意画面に渡された署名付きトークンを検証して中身を返す。改ざんや有効期限切れは None。
    # Verify the signed token given to the consent screen and return its content; tampered or expired tokens give None.
    try:
        return _consent_serializer().loads(token, max_age=CONSENT_REQUEST_TTL_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def consent_details(token: str) -> dict[str, Any] | None:
    # 同意画面に表示する情報(クライアント名、ホスト、scope と説明、ローカル宛ての警告)を組み立てる。
    # Build what the consent screen shows: client name, hosts, scopes with labels, and a localhost warning.
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
        # 標準の空白区切りscopeとの互換性を保ち、構造化項目でブラウザーが各権限を表示できるようにする。
        # ``scope`` remains the OAuth-standard, space-delimited compatibility
        # field. The structured fields let browser clients present each grant
        # separately without parsing or inventing labels.
        "scope": " ".join(scopes),
        "scopes": scopes,
        "scope_labels": {scope: MCP_SCOPE_LABELS[scope] for scope in scopes},
        "localhost_warning": redirect_host.lower() in {"localhost", "127.0.0.1", "::1"},
    }


async def complete_consent(token: str, user_id: int, approved: bool) -> str | None:
    # 利用者の同意結果を受けて、クライアントへ戻すリダイレクト URL を返す。承認なら認可コード付き、拒否なら access_denied。
    # 要求が不正・期限切れ、ユーザーが未認証、他人の個人用クライアントのときは None を返して何も発行しない。
    # Return the redirect URL back to the client for the user's decision: with a code if approved, access_denied if refused.
    # Return None and issue nothing for an invalid/expired request, an unverified user, or another user's personal client.
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
    # 利用者が許可している接続(grant)の一覧を、画面表示用の辞書で返す。
    # Return the user's authorized connections (grants) as dicts for display.
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
    # 接続(grant)を失効させる。ID の形式が不正なら False。
    # Revoke a connection (grant); returns False when the ID is malformed.
    try:
        parsed_grant_id = UUID(grant_id)
    except (TypeError, ValueError):
        return False
    async with session_scope() as session, session.begin():
        return await _oauth_repository.revoke_connection(
            session, user_id, parsed_grant_id
        )


async def update_connection_display_name(user_id: int, grant_id: str, display_name: str) -> bool:
    """OAuth クライアント本来の名前を残したまま、利用者向けの別名を設定する。

    Set a user-facing alias while retaining the OAuth client's original name.
    """
    cleaned_name = _clean_user_label(display_name)
    try:
        parsed_grant_id = UUID(grant_id)
    except (TypeError, ValueError):
        return False
    async with session_scope() as session, session.begin():
        return await _oauth_repository.update_connection_display_name(
            session, user_id, parsed_grant_id, cleaned_name
        )


async def revoke_token_value(raw_token: str) -> None:
    # トークンの平文からダイジェストを求めて失効させる（OAuth の revoke エンドポイント用）。
    # Revoke a token by the digest of its plaintext value (for the OAuth revoke endpoint).
    async with session_scope() as session, session.begin():
        await _oauth_repository.revoke_token_value(session, _digest(raw_token))
