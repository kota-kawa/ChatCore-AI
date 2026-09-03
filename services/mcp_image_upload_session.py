"""Bounded temporary storage for chunked MCP image uploads."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - only relevant on non-POSIX hosts
    fcntl = None

from services.error_messages import (
    ERROR_MCP_PROMPT_IMAGE_TOO_LARGE,
    ERROR_MCP_PROMPT_IMAGE_UPLOAD_CHUNK_INVALID,
    ERROR_MCP_PROMPT_IMAGE_UPLOAD_CHUNK_ORDER,
    ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED,
    ERROR_MCP_PROMPT_IMAGE_UPLOAD_INCOMPLETE,
    ERROR_MCP_PROMPT_IMAGE_UPLOAD_LIMIT,
)
from services.mcp_prompt_publishing import MCP_PROMPT_IMAGE_BASE64_MAX_LENGTH
from services.prompt_attachment_storage import get_prompt_attachment_upload_root

MCP_IMAGE_UPLOAD_CHUNK_MAX_LENGTH = 192 * 1024
MCP_IMAGE_UPLOAD_TTL_SECONDS = 30 * 60
MCP_IMAGE_UPLOAD_MAX_ACTIVE_PER_USER = 3

_UPLOAD_DIRECTORY_NAME = ".mcp-image-uploads"
_UPLOAD_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
_STAGED_DIRECTORY_PATTERN = re.compile(
    r"^[a-f0-9]{32}(?:\.processing)?(?:\.deleting-[a-f0-9]{32})?$"
)
_BASE64_FRAGMENT_PATTERN = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")

logger = logging.getLogger(__name__)


def _upload_root() -> str:
    root = os.path.join(get_prompt_attachment_upload_root(), _UPLOAD_DIRECTORY_NAME)
    os.makedirs(root, mode=0o700, exist_ok=True)
    return root


def _owner_digest(user_id: int, client_id: str) -> str:
    owner = f"{int(user_id)}\0{str(client_id)}"
    return hashlib.sha256(owner.encode("utf-8")).hexdigest()


def _user_digest(user_id: int) -> str:
    return hashlib.sha256(str(int(user_id)).encode("ascii")).hexdigest()


def _session_directory(upload_id: str) -> str:
    normalized = str(upload_id or "").strip().lower()
    if not _UPLOAD_ID_PATTERN.fullmatch(normalized):
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED)
    return os.path.join(_upload_root(), normalized)


def _processing_directory(upload_id: str) -> str:
    return f"{_session_directory(upload_id)}.processing"


def _atomic_write_text(path: str, content: str) -> None:
    directory = os.path.dirname(path)
    fd, temporary_path = tempfile.mkstemp(prefix=".mcp-image-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as file_obj:
            file_obj.write(content)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
        raise


def _metadata_path(directory: str) -> str:
    return os.path.join(directory, "metadata.json")


def _read_metadata(directory: str) -> dict[str, Any]:
    try:
        with open(_metadata_path(directory), encoding="ascii") as file_obj:
            value = json.load(file_obj)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED) from exc
    if not isinstance(value, dict):
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED)
    return value


def _write_metadata(directory: str, metadata: dict[str, Any]) -> None:
    _atomic_write_text(
        _metadata_path(directory),
        json.dumps(metadata, separators=(",", ":"), sort_keys=True),
    )


@contextmanager
def _session_lock(directory: str):
    try:
        lock_file = open(os.path.join(directory, ".lock"), "a+b")
    except OSError as exc:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED) from exc
    with lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _user_lock(root: str, user_id: int):
    lock_path = os.path.join(root, f".user-{_user_digest(user_id)}.lock")
    with open(lock_path, "a+b") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _remove_session_directory(directory: str) -> None:
    if os.path.isdir(directory) and not os.path.islink(directory):
        shutil.rmtree(directory)


def _claim_session_for_removal(directory: str) -> str:
    """Atomically hide a session before removing it outside the session lock."""
    claimed_directory = f"{directory}.deleting-{uuid4().hex}"
    try:
        os.replace(directory, claimed_directory)
    except OSError as exc:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED) from exc
    return claimed_directory


def _metadata_is_expired(metadata: dict[str, Any], now: float) -> bool:
    try:
        created_at = float(metadata["created_at"])
    except (KeyError, TypeError, ValueError):
        return True
    return created_at + MCP_IMAGE_UPLOAD_TTL_SECONDS <= now


def cleanup_expired_mcp_image_uploads(*, now: float | None = None) -> int:
    """Delete expired or corrupt upload sessions from the shared staging root."""
    current_time = time.time() if now is None else float(now)
    deleted = 0
    for entry in os.scandir(_upload_root()):
        if not _STAGED_DIRECTORY_PATTERN.fullmatch(entry.name) or not entry.is_dir(follow_symlinks=False):
            continue
        try:
            with _session_lock(entry.path):
                try:
                    metadata = _read_metadata(entry.path)
                except ValueError:
                    metadata = {}
                is_claimed_for_deletion = ".deleting-" in entry.name
                if not is_claimed_for_deletion and not _metadata_is_expired(metadata, current_time):
                    continue
                claimed_directory = (
                    entry.path
                    if is_claimed_for_deletion
                    else _claim_session_for_removal(entry.path)
                )
        except ValueError:
            continue
        try:
            _remove_session_directory(claimed_directory)
        except OSError:
            logger.warning("Failed to remove an expired MCP image upload.", exc_info=True)
            continue
        deleted += 1
    return deleted


def create_mcp_image_upload(
    user_id: int,
    client_id: str,
    expected_base64_characters: int,
) -> str:
    """Create an actor-bound chunk upload session and return its opaque ID."""
    if (
        expected_base64_characters <= 0
        or expected_base64_characters % 4 != 0
        or expected_base64_characters > MCP_PROMPT_IMAGE_BASE64_MAX_LENGTH
    ):
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_CHUNK_INVALID)
    cleanup_expired_mcp_image_uploads()
    root = _upload_root()
    owner_digest = _owner_digest(user_id, client_id)
    user_digest = _user_digest(user_id)
    with _user_lock(root, user_id):
        active = 0
        for entry in os.scandir(root):
            if not _UPLOAD_ID_PATTERN.fullmatch(entry.name) or not entry.is_dir(follow_symlinks=False):
                continue
            try:
                if _read_metadata(entry.path).get("user_digest") == user_digest:
                    active += 1
            except ValueError:
                continue
        if active >= MCP_IMAGE_UPLOAD_MAX_ACTIVE_PER_USER:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_LIMIT)

        upload_id = uuid4().hex
        directory = os.path.join(root, upload_id)
        os.mkdir(directory, mode=0o700)
        try:
            _write_metadata(
                directory,
                {
                    "created_at": time.time(),
                    "expected_characters": expected_base64_characters,
                    "next_chunk_index": 0,
                    "owner_digest": owner_digest,
                    "total_characters": 0,
                    "user_digest": user_digest,
                },
            )
        except Exception:
            _remove_session_directory(directory)
            raise
    return upload_id


def _read_owned_metadata(directory: str, user_id: int, client_id: str) -> dict[str, Any]:
    metadata = _read_metadata(directory)
    if (
        metadata.get("owner_digest") != _owner_digest(user_id, client_id)
        or _metadata_is_expired(metadata, time.time())
    ):
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED)
    return metadata


def append_mcp_image_upload_chunk(
    upload_id: str,
    user_id: int,
    client_id: str,
    chunk_index: int,
    chunk_base64: str,
) -> tuple[int, int]:
    """Append one ordered Base64 fragment, accepting identical retries."""
    normalized_chunk = "".join(str(chunk_base64 or "").split())
    if (
        not normalized_chunk
        or len(normalized_chunk) > MCP_IMAGE_UPLOAD_CHUNK_MAX_LENGTH
        or not _BASE64_FRAGMENT_PATTERN.fullmatch(normalized_chunk)
    ):
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_CHUNK_INVALID)

    directory = _session_directory(upload_id)
    with _session_lock(directory):
        metadata = _read_owned_metadata(directory, user_id, client_id)
        try:
            expected_characters = int(metadata["expected_characters"])
            next_chunk_index = int(metadata["next_chunk_index"])
            total_characters = int(metadata["total_characters"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED) from exc
        if chunk_index < 0 or chunk_index > next_chunk_index:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_CHUNK_ORDER)

        chunk_path = os.path.join(directory, f"chunk-{chunk_index:04d}.txt")
        if chunk_index < next_chunk_index:
            try:
                with open(chunk_path, encoding="ascii") as file_obj:
                    previous_chunk = file_obj.read()
            except OSError as exc:
                raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED) from exc
            if previous_chunk != normalized_chunk:
                raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_CHUNK_ORDER)
            return next_chunk_index, total_characters

        new_total = total_characters + len(normalized_chunk)
        if new_total > expected_characters:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_CHUNK_INVALID)
        if new_total > MCP_PROMPT_IMAGE_BASE64_MAX_LENGTH:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_TOO_LARGE)
        _atomic_write_text(chunk_path, normalized_chunk)
        metadata["next_chunk_index"] = next_chunk_index + 1
        metadata["total_characters"] = new_total
        _write_metadata(directory, metadata)
        return next_chunk_index + 1, new_total


def consume_mcp_image_upload(user_id: int, client_id: str, upload_id: str) -> str:
    """Atomically close and return a complete actor-owned Base64 upload."""
    directory = _session_directory(upload_id)
    with _session_lock(directory):
        metadata = _read_owned_metadata(directory, user_id, client_id)
        try:
            expected_characters = int(metadata["expected_characters"])
            next_chunk_index = int(metadata["next_chunk_index"])
            total_characters = int(metadata["total_characters"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED) from exc
        if next_chunk_index <= 0:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_CHUNK_INVALID)
        if total_characters != expected_characters:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_INCOMPLETE)
        chunks: list[str] = []
        try:
            for index in range(next_chunk_index):
                with open(
                    os.path.join(directory, f"chunk-{index:04d}.txt"),
                    encoding="ascii",
                ) as file_obj:
                    chunks.append(file_obj.read())
        except OSError as exc:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED) from exc
        try:
            os.replace(directory, _processing_directory(upload_id))
        except OSError as exc:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED) from exc
        return "".join(chunks)


def delete_mcp_image_upload(upload_id: str, user_id: int, client_id: str) -> None:
    """Delete an actor-owned staging session after publication or cancellation."""
    directory = _session_directory(upload_id)
    with _session_lock(directory):
        _read_owned_metadata(directory, user_id, client_id)
        claimed_directory = _claim_session_for_removal(directory)
    _remove_session_directory(claimed_directory)


def delete_consumed_mcp_image_upload(upload_id: str, user_id: int, client_id: str) -> None:
    """Delete a processing upload without allowing its content to be reused."""
    directory = _processing_directory(upload_id)
    with _session_lock(directory):
        metadata = _read_metadata(directory)
        if metadata.get("owner_digest") != _owner_digest(user_id, client_id):
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED)
        claimed_directory = _claim_session_for_removal(directory)
    _remove_session_directory(claimed_directory)
