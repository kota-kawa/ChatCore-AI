"""任意で有効にするリモート MCP サーバーの実行時設定（公開URL、許可ホスト、レート制限など）を環境変数から読む。

Runtime configuration for the optional remote MCP server (public URL, allowed hosts, rate limits and so on),
read from environment variables.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from services.env_settings import env_bool, env_int
from services.runtime_config import is_production_env
from services.web_urls import frontend_base_url

DEFAULT_MCP_DCR_RATE_LIMIT_PER_HOUR = 20
DEFAULT_MCP_AUTHORIZE_RATE_LIMIT_PER_10_MINUTES = 30
# MCP は SKILL のリソースを含む公開投稿を受け付けるため、通常の JSON-RPC
# リクエストより大きい本文を許容する。個々の投稿モデルでも別途検証する。
DEFAULT_MCP_MACHINE_MAX_BODY_BYTES = 8 * 1024 * 1024
DEFAULT_MCP_PUBLISH_RATE_LIMIT_PER_HOUR = 500
DEFAULT_MCP_PUBLISH_RATE_LIMIT_PER_DAY = 5_000
DEFAULT_MCP_CIMD_CACHE_ENTRIES = 256
DEFAULT_MCP_CIMD_MAX_CONCURRENT_FETCHES = 4


def is_mcp_enabled() -> bool:
    # MCP_ENABLED が真のときだけリモート MCP サーバーを有効にする。
    # The remote MCP server is enabled only when MCP_ENABLED is truthy.
    return env_bool("MCP_ENABLED")


def get_mcp_public_base_url() -> str:
    # MCP の公開ベース URL を返す。パスやクエリ、認証情報を含む値と、本番での非 HTTPS は設定ミスとして拒否する。
    # Return the public base URL for MCP; a path, query or credentials, and non-HTTPS in production,
    # are rejected as misconfiguration.
    value = (os.getenv("MCP_PUBLIC_BASE_URL") or frontend_base_url()).strip().rstrip("/")
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
    ):
        raise ValueError("MCP_PUBLIC_BASE_URL must be an absolute HTTP(S) URL.")
    if is_production_env() and parsed.scheme != "https":
        raise ValueError("MCP_PUBLIC_BASE_URL must use HTTPS in production.")
    return value


def get_mcp_server_url() -> str:
    return f"{get_mcp_public_base_url()}/mcp"


def get_mcp_encryption_keys() -> list[str]:
    # OAuth の保存データ暗号化に使う Fernet 鍵をカンマ区切りで読む（MultiFernet のため先頭の鍵で暗号化し、残りは復号用）。
    # Read the comma-separated Fernet keys for stored OAuth data (MultiFernet: the first encrypts,
    # the rest only decrypt); at least one is required.
    raw = os.getenv("MCP_OAUTH_ENCRYPTION_KEYS", "")
    keys = [value.strip() for value in raw.split(",") if value.strip()]
    if not keys:
        raise ValueError("MCP_OAUTH_ENCRYPTION_KEYS must contain at least one Fernet key.")
    return keys


def get_mcp_allowed_origins() -> list[str]:
    # 許可する Origin。未設定なら公開ベース URL だけを許可する。
    # Allowed Origins; when unset, only the public base URL is allowed.
    raw = os.getenv("MCP_ALLOWED_ORIGINS", "")
    configured = [value.strip() for value in raw.split(",") if value.strip()]
    if configured:
        return configured
    return [get_mcp_public_base_url()]


def get_mcp_allowed_hosts() -> list[str]:
    """MCP の DNS リバインディング対策が受け付ける Host ヘッダの値を返す。

    既定は公開ホストと、その ``www`` 付き/なしの兄弟ホスト。どちらの形で設定したクライアントでも動き、
    両方を受ける nginx の ``server_name`` と揃う。``MCP_ALLOWED_HOSTS``（カンマ区切り）で上書きできる。

    Host header values accepted by the MCP DNS-rebinding protection.

    Defaults to the public host and its ``www``/apex sibling so a client
    configured with either form works — matching the nginx ``server_name`` that
    serves both. Override with ``MCP_ALLOWED_HOSTS`` (comma separated).
    """
    raw = os.getenv("MCP_ALLOWED_HOSTS", "")
    configured = [value.strip() for value in raw.split(",") if value.strip()]
    if configured:
        return configured
    host = urlparse(get_mcp_public_base_url()).netloc
    sibling = host[4:] if host.startswith("www.") else f"www.{host}"
    return [host, sibling]


# 以下は MCP の OAuth 入口、公開操作、クライアント情報取得に対する上限値を、環境変数または既定値から返す。
# The getters below return the limits for MCP OAuth entry points, publishing and client-metadata fetches, from env or defaults.
def get_mcp_dcr_rate_limit_per_hour() -> int:
    return env_int("MCP_DCR_RATE_LIMIT_PER_HOUR", DEFAULT_MCP_DCR_RATE_LIMIT_PER_HOUR)


def get_mcp_authorize_rate_limit_per_10_minutes() -> int:
    return env_int(
        "MCP_AUTHORIZE_RATE_LIMIT_PER_10_MINUTES",
        DEFAULT_MCP_AUTHORIZE_RATE_LIMIT_PER_10_MINUTES,
    )


def get_mcp_machine_max_body_bytes() -> int:
    return env_int("MCP_MACHINE_MAX_BODY_BYTES", DEFAULT_MCP_MACHINE_MAX_BODY_BYTES)


def get_mcp_publish_rate_limit_per_hour() -> int:
    return env_int(
        "MCP_PUBLISH_RATE_LIMIT_PER_HOUR",
        DEFAULT_MCP_PUBLISH_RATE_LIMIT_PER_HOUR,
    )


def get_mcp_publish_rate_limit_per_day() -> int:
    return env_int(
        "MCP_PUBLISH_RATE_LIMIT_PER_DAY",
        DEFAULT_MCP_PUBLISH_RATE_LIMIT_PER_DAY,
    )


def get_mcp_cimd_cache_entries() -> int:
    return env_int("MCP_CIMD_CACHE_ENTRIES", DEFAULT_MCP_CIMD_CACHE_ENTRIES)


def get_mcp_cimd_max_concurrent_fetches() -> int:
    return env_int(
        "MCP_CIMD_MAX_CONCURRENT_FETCHES",
        DEFAULT_MCP_CIMD_MAX_CONCURRENT_FETCHES,
    )
