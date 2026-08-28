"""MCP-specific decoding and persistence for prompt-share images."""

from __future__ import annotations

import base64
import binascii
import re

from services.error_messages import (
    ERROR_MCP_PROMPT_IMAGE_BASE64_INVALID,
    ERROR_MCP_PROMPT_IMAGE_DATA_URL_INVALID,
    ERROR_MCP_PROMPT_IMAGE_FORMAT_UNKNOWN,
    ERROR_MCP_PROMPT_IMAGE_METADATA_MISMATCH,
    ERROR_MCP_PROMPT_IMAGE_MIME_UNSUPPORTED,
    ERROR_MCP_PROMPT_IMAGE_TOO_LARGE,
    ERROR_PROMPT_ATTACHMENT_EMPTY,
    ERROR_PROMPT_ATTACHMENT_FORMAT_MISMATCH,
)
from services.prompt_attachment_storage import PROMPT_ATTACHMENT_MAX_BYTES
from services.prompt_attachment_upload import (
    infer_prompt_attachment_mime_type,
    save_prompt_attachment,
)

MCP_PROMPT_IMAGE_BASE64_MAX_LENGTH = ((PROMPT_ATTACHMENT_MAX_BYTES + 2) // 3) * 4 + 64
MCP_PROMPT_IMAGE_FILENAME_MAX_LENGTH = 255
MCP_PROMPT_IMAGE_MIME_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif"}
)
_DATA_URL_PATTERN = re.compile(r"^data:(?P<mime>[^;,]+);base64,(?P<data>.*)$", re.IGNORECASE | re.DOTALL)
_MIME_TO_EXTENSION = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _decode_mcp_image_base64(image_base64: str) -> tuple[bytes, str | None]:
    """Decode a strict Base64 image value, accepting an optional data URL prefix."""
    encoded = "".join(str(image_base64 or "").split())
    if not encoded:
        raise ValueError(ERROR_PROMPT_ATTACHMENT_EMPTY)

    data_url_match = _DATA_URL_PATTERN.fullmatch(encoded)
    data_url_mime: str | None = None
    if data_url_match is not None:
        data_url_mime = data_url_match.group("mime").strip().lower()
        if data_url_mime not in MCP_PROMPT_IMAGE_MIME_TYPES:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_MIME_UNSUPPORTED)
        encoded = data_url_match.group("data")
    elif encoded.lower().startswith("data:"):
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_DATA_URL_INVALID)

    if len(encoded) > MCP_PROMPT_IMAGE_BASE64_MAX_LENGTH:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_TOO_LARGE)
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_BASE64_INVALID) from exc
    if not decoded:
        raise ValueError(ERROR_PROMPT_ATTACHMENT_EMPTY)
    if len(decoded) > PROMPT_ATTACHMENT_MAX_BYTES:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_TOO_LARGE)
    return decoded, data_url_mime


def save_mcp_prompt_image(
    image_base64: str,
    user_id: int,
    *,
    filename: str = "",
    mime_type: str = "",
) -> dict[str, str]:
    """Decode and save one MCP prompt reference image through the shared upload boundary."""
    source, data_url_mime = _decode_mcp_image_base64(image_base64)
    declared_mime = str(mime_type or "").strip().lower()
    if declared_mime and declared_mime not in MCP_PROMPT_IMAGE_MIME_TYPES:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_MIME_UNSUPPORTED)
    if data_url_mime and declared_mime and data_url_mime != declared_mime:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_METADATA_MISMATCH)
    detected_mime = infer_prompt_attachment_mime_type(source)
    if detected_mime is None:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_FORMAT_UNKNOWN)
    resolved_mime = declared_mime or data_url_mime or detected_mime
    if resolved_mime != detected_mime:
        raise ValueError(ERROR_PROMPT_ATTACHMENT_FORMAT_MISMATCH)

    resolved_filename = str(filename or "").strip()
    if not resolved_filename:
        resolved_filename = f"reference{_MIME_TO_EXTENSION[resolved_mime]}"
    return save_prompt_attachment(
        source,
        user_id,
        "image",
        filename=resolved_filename,
        content_type=resolved_mime,
    )
