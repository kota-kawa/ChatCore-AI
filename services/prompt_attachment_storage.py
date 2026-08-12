"""Filesystem paths and public URLs for prompt-share media attachments."""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from services.web_constants import BASE_DIR


PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV = "PROMPT_SHARE_UPLOAD_DIR"
PROMPT_ATTACHMENT_PUBLIC_URL_PREFIX = "/prompt_share/api/media"
LEGACY_PROMPT_ATTACHMENT_URL_PREFIX = "/static/uploads/prompt_share"

_DEFAULT_PROMPT_ATTACHMENT_UPLOAD_ROOT = os.path.join(
    BASE_DIR,
    "data",
    "uploads",
    "prompt_share",
)
_SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_IMAGE_CONTENT_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def get_prompt_attachment_upload_root() -> str:
    """Return the configured absolute storage directory for prompt attachments."""
    configured = str(os.getenv(PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV, "") or "").strip()
    if not configured:
        return os.path.abspath(_DEFAULT_PROMPT_ATTACHMENT_UPLOAD_ROOT)
    if not os.path.isabs(configured):
        configured = os.path.join(BASE_DIR, configured)
    return os.path.abspath(configured)


def validate_prompt_attachment_filename(filename: object) -> str:
    """Validate a single image filename before resolving it below the upload root."""
    value = str(filename or "").strip()
    if (
        not value
        or not _SAFE_FILENAME_PATTERN.fullmatch(value)
        or os.path.basename(value) != value
        or os.path.splitext(value)[1].lower() not in _IMAGE_CONTENT_TYPES
    ):
        raise ValueError("Invalid prompt attachment filename.")
    return value


def resolve_prompt_attachment_path(filename: object) -> str:
    """Resolve a validated filename while preventing traversal and symlink escapes."""
    safe_filename = validate_prompt_attachment_filename(filename)
    root = os.path.realpath(get_prompt_attachment_upload_root())
    candidate = os.path.realpath(os.path.join(root, safe_filename))
    if os.path.commonpath((root, candidate)) != root:
        raise ValueError("Invalid prompt attachment path.")
    return candidate


def resolve_legacy_prompt_attachment_path(filename: object) -> str:
    """Resolve a validated filename below the former frontend/public location."""
    safe_filename = validate_prompt_attachment_filename(filename)
    root = os.path.realpath(
        os.path.join(
            BASE_DIR,
            "frontend",
            "public",
            "static",
            "uploads",
            "prompt_share",
        )
    )
    candidate = os.path.realpath(os.path.join(root, safe_filename))
    if os.path.commonpath((root, candidate)) != root:
        raise ValueError("Invalid legacy prompt attachment path.")
    return candidate


def prompt_attachment_content_type(filename: object) -> str:
    """Return a deterministic image Content-Type from a validated extension."""
    safe_filename = validate_prompt_attachment_filename(filename)
    return _IMAGE_CONTENT_TYPES[os.path.splitext(safe_filename)[1].lower()]


def build_prompt_attachment_public_url(filename: object) -> str:
    """Build the backend-served public URL for a stored attachment."""
    safe_filename = validate_prompt_attachment_filename(filename)
    return f"{PROMPT_ATTACHMENT_PUBLIC_URL_PREFIX}/{safe_filename}"


def prompt_attachment_filename_from_url(url: object) -> str | None:
    """Extract a safe filename from either the current or legacy relative URL."""
    raw_url = str(url or "").strip()
    if not raw_url:
        return None
    parsed_url = urlsplit(raw_url)
    if parsed_url.scheme or parsed_url.netloc:
        return None
    path = parsed_url.path
    for prefix in (
        PROMPT_ATTACHMENT_PUBLIC_URL_PREFIX,
        LEGACY_PROMPT_ATTACHMENT_URL_PREFIX,
    ):
        expected_prefix = f"{prefix}/"
        if not path.startswith(expected_prefix):
            continue
        filename = path[len(expected_prefix) :]
        try:
            return validate_prompt_attachment_filename(filename)
        except ValueError:
            return None
    return None


def normalize_prompt_attachment_public_url(url: object) -> str | None:
    """Convert a recognized legacy/current attachment URL to its canonical URL."""
    filename = prompt_attachment_filename_from_url(url)
    if filename is None:
        return None
    return build_prompt_attachment_public_url(filename)
