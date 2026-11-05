"""MCP 経由の画像アップロードを、分割(チャンク)送信された Base64 として一時保存する上限付きストレージ。

ユーザーごとのセッションディレクトリにチャンクを順に溜め、完了後に結合して返す。有効期限切れや壊れたセッションは掃除する。
Bounded temporary storage for MCP image uploads sent as chunked Base64.
Chunks accumulate in a per-session directory and are joined once complete; expired or corrupt sessions are cleaned up.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from contextlib import ExitStack, contextmanager
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
    # プロンプト添付の保存先配下に、所有者のみアクセスできる一時ディレクトリを用意する。
    # Ensure an owner-only staging directory under the prompt attachment upload root.
    root = os.path.join(get_prompt_attachment_upload_root(), _UPLOAD_DIRECTORY_NAME)
    os.makedirs(root, mode=0o700, exist_ok=True)
    return root


def _owner_digest(user_id: int, client_id: str) -> str:
    # ユーザーと MCP クライアントの組をハッシュ化し、メタデータに生の ID を残さず所有者を照合する。
    # Hash the (user, MCP client) pair so ownership can be checked without storing raw IDs in metadata.
    owner = f"{int(user_id)}\0{client_id!s}"
    return hashlib.sha256(owner.encode("utf-8")).hexdigest()


def _user_digest(user_id: int) -> str:
    # ユーザー単位の同時アップロード数を数えるためのハッシュ。
    # Per-user hash used to count that user's concurrent uploads.
    return hashlib.sha256(str(int(user_id)).encode("ascii")).hexdigest()


def _session_directory(upload_id: str) -> str:
    # upload_id は 32 桁の16進に限定し、パス区切りなどによるディレクトリ外への参照を防ぐ。
    # Restrict upload_id to 32 hex characters so it cannot escape the staging directory.
    normalized = str(upload_id or "").strip().lower()
    if not _UPLOAD_ID_PATTERN.fullmatch(normalized):
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED)
    return os.path.join(_upload_root(), normalized)


def _processing_directory(upload_id: str) -> str:
    # 取り出し済み(公開処理中)のセッションを置く、`.processing` 付きのディレクトリ名。
    # Directory name with the `.processing` suffix for a consumed session that is being published.
    return f"{_session_directory(upload_id)}.processing"


def _atomic_write_text(path: str, content: str) -> None:
    # 一時ファイルへ書いて fsync 後に置き換え、途中で落ちても中途半端なファイルを残さない。
    # Write to a temp file, fsync, then replace, so a crash never leaves a half-written file.
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
    # セッションの metadata.json を読む。読めない・壊れている場合は期限切れ扱いにする。
    # Read the session's metadata.json; unreadable or corrupt metadata is treated as expired.
    try:
        with open(_metadata_path(directory), encoding="ascii") as file_obj:
            value = json.load(file_obj)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED) from exc
    # このモジュールは全ての失敗を ValueError で表現し、呼び出し元（services/mcp_server.py）が
    # ValueError だけを捕捉してユーザー向けメッセージへ変換するため、型不一致でも ValueError を保つ。
    # This module reports every failure as ValueError because its caller (services/mcp_server.py)
    # catches only ValueError to build the user-facing message, so keep it even for a type mismatch.
    if not isinstance(value, dict):
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED)  # noqa: TRY004
    return value


def _write_metadata(directory: str, metadata: dict[str, Any]) -> None:
    _atomic_write_text(
        _metadata_path(directory),
        json.dumps(metadata, separators=(",", ":"), sort_keys=True),
    )


@contextmanager
def _session_lock(directory: str):
    # セッション単位の排他ロック。同じアップロードへの並行リクエストでチャンクやメタデータが競合しないようにする。
    # Per-session exclusive lock so concurrent requests on one upload cannot race on chunks or metadata.
    with ExitStack() as stack:
        # ロックファイルを開く段階の OSError だけをアップロード期限切れエラーへ変換する。
        # ExitStack が確実にクローズするため、ロック本体の例外はそのまま呼び出し元へ伝える。
        # Convert only an OSError from opening the lock file into the upload-expired error.
        # ExitStack guarantees the close, and errors from the locked body propagate unchanged.
        try:
            lock_file = stack.enter_context(open(os.path.join(directory, ".lock"), "a+b"))
        except OSError as exc:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED) from exc
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _user_lock(root: str, user_id: int):
    # ユーザー単位の排他ロック。同時アップロード数の確認と新規作成を不可分にして上限を超えさせない。
    # Per-user exclusive lock making the active-upload count check and creation atomic, so the cap holds.
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
    # シンボリックリンクは辿らず、通常のディレクトリだけを削除する。
    # Remove only real directories, never following symbolic links.
    if os.path.isdir(directory) and not os.path.islink(directory):
        shutil.rmtree(directory)


def _claim_session_for_removal(directory: str) -> str:
    """セッションを原子的にリネームして見えなくし、セッションロックの外で削除できるようにする。

    Atomically hide a session before removing it outside the session lock.
    """
    claimed_directory = f"{directory}.deleting-{uuid4().hex}"
    try:
        os.replace(directory, claimed_directory)
    except OSError as exc:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED) from exc
    return claimed_directory


def _metadata_is_expired(metadata: dict[str, Any], now: float) -> bool:
    # 作成時刻が読めないメタデータは期限切れとして扱う。
    # Metadata without a readable creation time counts as expired.
    try:
        created_at = float(metadata["created_at"])
    except (KeyError, TypeError, ValueError):
        return True
    return created_at + MCP_IMAGE_UPLOAD_TTL_SECONDS <= now


def cleanup_expired_mcp_image_uploads(*, now: float | None = None) -> int:
    """共有ステージング領域から、期限切れまたは壊れたアップロードセッションを削除し、削除数を返す。

    Delete expired or corrupt upload sessions from the shared staging root.
    """
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
    """ユーザーとクライアントに結び付いたチャンクアップロードのセッションを作り、不透明な ID を返す。

    Create an actor-bound chunk upload session and return its opaque ID.
    """
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
    # 所有者が一致し期限内のときだけメタデータを返す。他人のセッションも「期限切れ」と同じ失敗にして存在を悟らせない。
    # Return metadata only for the owner and within the TTL; a foreign session fails like an expired one so its existence is not revealed.
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
    """順序付きの Base64 断片を1つ追記する。同じ内容の再送は受け付ける。

    Append one ordered Base64 fragment, accepting identical retries.
    """
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
        # 既に受け取ったチャンクの再送は、内容が同じなら冪等に成功させ、違えば順序エラーにする。
        # A resent chunk already received succeeds idempotently if identical, otherwise it is an order error.
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
    """完了した自分のアップロードを原子的に閉じ、結合した Base64 を返す。

    Atomically close and return a complete actor-owned Base64 upload.
    """
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
        # 取り出したセッションは `.processing` へ移し、同じ内容を二重に取り出せないようにする。
        # Move the consumed session to `.processing` so the same content cannot be consumed twice.
        try:
            os.replace(directory, _processing_directory(upload_id))
        except OSError as exc:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED) from exc
        return "".join(chunks)


def delete_mcp_image_upload(upload_id: str, user_id: int, client_id: str) -> None:
    """公開後またはキャンセル時に、自分のステージングセッションを削除する。

    Delete an actor-owned staging session after publication or cancellation.
    """
    directory = _session_directory(upload_id)
    with _session_lock(directory):
        _read_owned_metadata(directory, user_id, client_id)
        claimed_directory = _claim_session_for_removal(directory)
    _remove_session_directory(claimed_directory)


def delete_consumed_mcp_image_upload(upload_id: str, user_id: int, client_id: str) -> None:
    """処理中(取り出し済み)のアップロードを、内容を再利用させずに削除する。

    Delete a processing upload without allowing its content to be reused.
    """
    directory = _processing_directory(upload_id)
    with _session_lock(directory):
        metadata = _read_metadata(directory)
        if metadata.get("owner_digest") != _owner_digest(user_id, client_id):
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_UPLOAD_EXPIRED)
        claimed_directory = _claim_session_for_removal(directory)
    _remove_session_directory(claimed_directory)
