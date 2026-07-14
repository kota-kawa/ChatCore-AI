"""Runtime configuration for the optional remote MCP server."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from services.runtime_config import is_production_env
from services.web_constants import FRONTEND_URL

DEFAULT_MCP_DCR_RATE_LIMIT_PER_HOUR = 20
DEFAULT_MCP_AUTHORIZE_RATE_LIMIT_PER_10_MINUTES = 30
DEFAULT_MCP_MACHINE_MAX_BODY_BYTES = 64 * 1024
DEFAULT_MCP_CIMD_CACHE_ENTRIES = 256
DEFAULT_MCP_CIMD_MAX_CONCURRENT_FETCHES = 4


def is_mcp_enabled() -> bool:
    return (os.getenv("MCP_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}


def get_mcp_public_base_url() -> str:
    value = (os.getenv("MCP_PUBLIC_BASE_URL") or FRONTEND_URL).strip().rstrip("/")
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
    raw = os.getenv("MCP_OAUTH_ENCRYPTION_KEYS", "")
    keys = [value.strip() for value in raw.split(",") if value.strip()]
    if not keys:
        raise ValueError("MCP_OAUTH_ENCRYPTION_KEYS must contain at least one Fernet key.")
    return keys


def get_mcp_allowed_origins() -> list[str]:
    raw = os.getenv("MCP_ALLOWED_ORIGINS", "")
    configured = [value.strip() for value in raw.split(",") if value.strip()]
    if configured:
        return configured
    return [get_mcp_public_base_url()]


def get_mcp_allowed_hosts() -> list[str]:
    """Host header values accepted by the MCP DNS-rebinding protection.

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


def _get_positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def get_mcp_dcr_rate_limit_per_hour() -> int:
    return _get_positive_int_env("MCP_DCR_RATE_LIMIT_PER_HOUR", DEFAULT_MCP_DCR_RATE_LIMIT_PER_HOUR)


def get_mcp_authorize_rate_limit_per_10_minutes() -> int:
    return _get_positive_int_env(
        "MCP_AUTHORIZE_RATE_LIMIT_PER_10_MINUTES",
        DEFAULT_MCP_AUTHORIZE_RATE_LIMIT_PER_10_MINUTES,
    )


def get_mcp_machine_max_body_bytes() -> int:
    return _get_positive_int_env("MCP_MACHINE_MAX_BODY_BYTES", DEFAULT_MCP_MACHINE_MAX_BODY_BYTES)


def get_mcp_cimd_cache_entries() -> int:
    return _get_positive_int_env("MCP_CIMD_CACHE_ENTRIES", DEFAULT_MCP_CIMD_CACHE_ENTRIES)


def get_mcp_cimd_max_concurrent_fetches() -> int:
    return _get_positive_int_env(
        "MCP_CIMD_MAX_CONCURRENT_FETCHES",
        DEFAULT_MCP_CIMD_MAX_CONCURRENT_FETCHES,
    )
