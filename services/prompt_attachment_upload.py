"""Validation and persistence for prompt-share image uploads."""

from __future__ import annotations

import os

from werkzeug.utils import secure_filename

from services.error_messages import (
    ERROR_PROMPT_ATTACHMENT_EMPTY,
    ERROR_PROMPT_ATTACHMENT_FORMAT_MISMATCH,
    ERROR_PROMPT_ATTACHMENT_FILENAME_INVALID,
    ERROR_PROMPT_ATTACHMENT_MEDIA_UNSUPPORTED,
    ERROR_PROMPT_ATTACHMENT_MIME_UNSUPPORTED,
)
from services.prompt_attachment_processing import process_prompt_attachment
from services.prompt_attachment_storage import (
    PROMPT_ATTACHMENT_MAX_BYTES,
    build_prompt_attachment_public_url,
    get_prompt_attachment_storage,
    prompt_attachment_content_type,
)
from services.prompt_types import get_attachment_rule


def _prompt_attachment_signature_matches(extension: str, prefix: bytes) -> bool:
    """Confirm that the uploaded bytes match the filename's image extension."""
    if extension == ".png":
        return prefix.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {".jpg", ".jpeg"}:
        return prefix.startswith(b"\xff\xd8\xff")
    if extension == ".gif":
        return prefix.startswith((b"GIF87a", b"GIF89a"))
    if extension == ".webp":
        return len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP"
    return False


def save_prompt_attachment(
    source: bytes,
    user_id: int,
    media_type: str,
    *,
    filename: str,
    content_type: str = "",
) -> dict[str, str]:
    """Validate, normalize, and persist one prompt-share image attachment."""
    rule = get_attachment_rule(media_type)
    if rule is None:
        raise ValueError(ERROR_PROMPT_ATTACHMENT_MEDIA_UNSUPPORTED)

    safe_filename = secure_filename(filename or "")
    if not safe_filename:
        raise ValueError(ERROR_PROMPT_ATTACHMENT_FILENAME_INVALID)
    extension = os.path.splitext(safe_filename)[1].lower()
    if extension not in rule.accepted_ext:
        allowed = " / ".join(sorted({ext.lstrip(".").upper() for ext in rule.accepted_ext}))
        raise ValueError(f"添付は {allowed} のいずれかを指定してください。")

    normalized_content_type = str(content_type or "").strip().lower()
    if normalized_content_type and normalized_content_type not in rule.accepted_mime:
        raise ValueError(ERROR_PROMPT_ATTACHMENT_MIME_UNSUPPORTED)
    if not isinstance(source, bytes):
        source = bytes(source)
    max_bytes = min(rule.max_bytes, PROMPT_ATTACHMENT_MAX_BYTES)
    if len(source) > max_bytes:
        raise ValueError(f"添付ファイルのサイズは{max_bytes // (1024 * 1024)}MB以下にしてください。")
    if not source:
        raise ValueError(ERROR_PROMPT_ATTACHMENT_EMPTY)
    if not _prompt_attachment_signature_matches(extension, source[:16]):
        raise ValueError(ERROR_PROMPT_ATTACHMENT_FORMAT_MISMATCH)

    processed = process_prompt_attachment(source)
    stored = get_prompt_attachment_storage().save_variants(
        user_id,
        processed.display_bytes,
        processed.thumbnail_bytes,
    )
    return {
        "url": build_prompt_attachment_public_url(stored.display_filename),
        "thumbnail_url": build_prompt_attachment_public_url(stored.thumbnail_filename),
        "role": rule.role,
        "media_type": prompt_attachment_content_type(stored.display_filename),
        "width": str(processed.width),
        "height": str(processed.height),
        "size_bytes": str(stored.display_size_bytes),
    }


def infer_prompt_attachment_mime_type(source: bytes) -> str | None:
    """Return an accepted image MIME type from a file signature when possible."""
    prefix = source[:16]
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if prefix.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
        return "image/webp"
    return None
