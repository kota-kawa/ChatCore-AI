"""Runtime configuration for the optional remote MCP server."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from services.runtime_config import is_production_env
from services.web_constants import FRONTEND_URL


def is_mcp_enabled() -> bool:
    return (os.getenv("MCP_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}


def get_mcp_public_base_url() -> str:
    value = (os.getenv("MCP_PUBLIC_BASE_URL") or FRONTEND_URL).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
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
