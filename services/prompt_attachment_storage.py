"""Filesystem paths and public URLs for prompt-share media attachments."""

from __future__ import annotations

import os
import re
import tempfile
import time
from urllib.parse import urlsplit
from dataclasses import dataclass
from typing import Any, Protocol
from contextlib import contextmanager
from uuid import uuid4

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - only relevant on non-POSIX hosts
    fcntl = None

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


def _positive_int_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


PROMPT_ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024
PROMPT_ATTACHMENT_MAX_REQUEST_BYTES = 6 * 1024 * 1024
PROMPT_ATTACHMENT_USER_QUOTA_BYTES = _positive_int_env(
    "PROMPT_SHARE_ATTACHMENT_USER_QUOTA_BYTES",
    100 * 1024 * 1024,
)
PROMPT_ATTACHMENT_ORPHAN_GRACE_SECONDS = 60 * 60


@dataclass(frozen=True)
class StoredPromptAttachment:
    """Storage-neutral result of persisting normalized image variants."""

    display_filename: str
    thumbnail_filename: str
    display_size_bytes: int
    thumbnail_size_bytes: int


class PromptAttachmentStorage(Protocol):
    """Boundary implemented by local disk today and object storage in the future."""

    def save_variants(
        self,
        user_id: int,
        display_bytes: bytes,
        thumbnail_bytes: bytes,
    ) -> StoredPromptAttachment: ...

    def resolve_path(self, filename: object) -> str: ...

    def delete_attachment(self, attachment: object) -> int: ...

    def cleanup_unreferenced(self, attachments: list[dict[str, Any]]) -> int: ...


class LocalPromptAttachmentStorage:
    """Atomic filesystem backend for normalized prompt-share image variants."""

    def save_variants(
        self,
        user_id: int,
        display_bytes: bytes,
        thumbnail_bytes: bytes,
    ) -> StoredPromptAttachment:
        root = get_prompt_attachment_upload_root()
        os.makedirs(root, exist_ok=True)
        total_new_bytes = len(display_bytes) + len(thumbnail_bytes)
        if total_new_bytes <= 0:
            raise ValueError("画像の変換結果が空です。")

        with _user_quota_lock(root, int(user_id)):
            current_usage = _local_user_usage_bytes(root, int(user_id))
            if current_usage + total_new_bytes > PROMPT_ATTACHMENT_USER_QUOTA_BYTES:
                quota_mb = PROMPT_ATTACHMENT_USER_QUOTA_BYTES // (1024 * 1024)
                raise ValueError(
                    f"画像保存容量の上限（{quota_mb}MB）に達しています。不要な投稿を削除してから再試行してください。"
                )

            token = _random_token()
            display_filename = f"user_{int(user_id)}_{token}.webp"
            thumbnail_filename = f"user_{int(user_id)}_{token}_card.webp"
            display_path = self.resolve_path(display_filename)
            thumbnail_path = self.resolve_path(thumbnail_filename)
            try:
                _atomic_write(display_path, display_bytes)
                _atomic_write(thumbnail_path, thumbnail_bytes)
            except Exception:
                for path in (display_path, thumbnail_path):
                    if os.path.isfile(path):
                        os.remove(path)
                raise
            return StoredPromptAttachment(
                display_filename=display_filename,
                thumbnail_filename=thumbnail_filename,
                display_size_bytes=len(display_bytes),
                thumbnail_size_bytes=len(thumbnail_bytes),
            )

    def resolve_path(self, filename: object) -> str:
        return resolve_prompt_attachment_path(filename)

    def delete_attachment(self, attachment: object) -> int:
        deleted = 0
        if not isinstance(attachment, dict):
            return deleted
        filenames = {
            prompt_attachment_filename_from_url(attachment.get("url")),
            prompt_attachment_filename_from_url(attachment.get("thumbnail_url")),
        }
        for filename in filenames:
            if filename is None:
                continue
            try:
                filepath = self.resolve_path(filename)
            except ValueError:
                continue
            if os.path.isfile(filepath):
                os.remove(filepath)
                deleted += 1
        return deleted

    def cleanup_unreferenced(self, attachments: list[dict[str, Any]]) -> int:
        referenced = {
            filename
            for attachment in attachments
            for filename in (
                prompt_attachment_filename_from_url(attachment.get("url")),
                prompt_attachment_filename_from_url(attachment.get("thumbnail_url")),
            )
            if filename is not None
        }
        root = get_prompt_attachment_upload_root()
        if not os.path.isdir(root):
            return 0
        cutoff = time.time() - PROMPT_ATTACHMENT_ORPHAN_GRACE_SECONDS
        deleted = 0
        for entry in os.scandir(root):
            if not entry.is_file() or entry.name in referenced:
                continue
            try:
                validate_prompt_attachment_filename(entry.name)
            except ValueError:
                continue
            if entry.stat().st_mtime > cutoff:
                continue
            os.remove(entry.path)
            deleted += 1
        return deleted


_local_storage = LocalPromptAttachmentStorage()


def get_prompt_attachment_storage() -> PromptAttachmentStorage:
    """Return the active backend; swap this factory during object-store migration."""
    return _local_storage


def get_prompt_attachment_upload_root() -> str:
    """Return the configured absolute storage directory for prompt attachments."""
    configured = str(os.getenv(PROMPT_ATTACHMENT_UPLOAD_ROOT_ENV, "") or "").strip()
    if not configured:
        return os.path.abspath(_DEFAULT_PROMPT_ATTACHMENT_UPLOAD_ROOT)
    if not os.path.isabs(configured):
        configured = os.path.join(BASE_DIR, configured)
    return os.path.abspath(configured)


def _random_token() -> str:
    return uuid4().hex


def _atomic_write(destination: str, content: bytes) -> None:
    """Write a variant atomically so readers never observe a partial image."""
    directory = os.path.dirname(destination)
    fd, temporary_path = tempfile.mkstemp(prefix=".prompt-upload-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as file_obj:
            file_obj.write(content)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(temporary_path, destination)
    except Exception:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
        raise


@contextmanager
def _user_quota_lock(root: str, user_id: int):
    """Serialize same-user quota checks across local Uvicorn worker processes."""
    lock_path = os.path.join(root, f".prompt-share-user-{user_id}.lock")
    with open(lock_path, "a+b") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _local_user_usage_bytes(root: str, user_id: int) -> int:
    prefix = f"user_{user_id}_"
    total = 0
    for entry in os.scandir(root):
        if not entry.is_file() or not entry.name.startswith(prefix):
            continue
        try:
            validate_prompt_attachment_filename(entry.name)
        except ValueError:
            continue
        total += entry.stat().st_size
    return total


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


def delete_prompt_attachment(attachment: object) -> int:
    """Remove every local variant referenced by one attachment descriptor."""
    return get_prompt_attachment_storage().delete_attachment(attachment)


def cleanup_unreferenced_prompt_attachments(attachments: list[dict[str, Any]]) -> int:
    """Reconcile local storage against attachment descriptors from active prompts."""
    return get_prompt_attachment_storage().cleanup_unreferenced(attachments)
