"""Private filesystem storage for images attached to chat messages.

チャットに添付した画像は本人の会話でだけ使う私的なデータなので、プロンプト共有の
画像（公開URLで配信）とは別の保存先に置き、配信時に持ち主を照合する。持ち主は
画像IDの先頭に埋め込んだ HMAC で判定するため、配信のたびに DB を引かずに済み、
DB に行を持たない一時ルーム・ゲストの画像にも同じ規則を使える。

Chat images are private to the conversation they belong to, so they live apart from
the publicly served prompt-share media. The owner is encoded as an HMAC prefix of the
image id, which lets delivery check ownership without a database lookup and works the
same for temporary and guest rooms that have no database rows.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import tempfile
import time
from collections.abc import Iterable
from uuid import uuid4

from services.runtime_config import get_session_secret_key
from services.web_constants import BASE_DIR

CHAT_IMAGE_UPLOAD_ROOT_ENV = "CHAT_IMAGE_UPLOAD_DIR"

_DEFAULT_CHAT_IMAGE_UPLOAD_ROOT = os.path.join(BASE_DIR, "data", "uploads", "chat_images")
_OWNER_DIGEST_LENGTH = 16
_CHAT_IMAGE_ID_PATTERN = re.compile(r"^[0-9a-f]{48}$")
_DISPLAY_SUFFIX = ".webp"
_THUMBNAIL_SUFFIX = "_thumb.webp"
# 秘密鍵が無い開発環境でも ID の形は保つ。本番は app.py が FASTAPI_SECRET_KEY を必須にしている。
# Keeps the id shape in development without a key; app.py requires FASTAPI_SECRET_KEY in production.
_DEVELOPMENT_OWNER_SECRET = "chat-image-development-owner-secret"


def get_chat_image_upload_root() -> str:
    """Return the configured absolute storage directory for chat images."""
    configured = str(os.getenv(CHAT_IMAGE_UPLOAD_ROOT_ENV, "") or "").strip()
    if not configured:
        return os.path.abspath(_DEFAULT_CHAT_IMAGE_UPLOAD_ROOT)
    if not os.path.isabs(configured):
        configured = os.path.join(BASE_DIR, configured)
    return os.path.abspath(configured)


def chat_image_owner_key(*, user_id: object, sid: object) -> str | None:
    """Return the owner identity for images: the signed-in user, else the guest session."""
    if user_id is not None:
        return f"user:{int(user_id)}"
    if isinstance(sid, str) and sid:
        return f"guest:{sid}"
    return None


def _owner_digest(owner_key: str) -> str:
    secret = get_session_secret_key() or _DEVELOPMENT_OWNER_SECRET
    digest = hmac.new(secret.encode("utf-8"), owner_key.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:_OWNER_DIGEST_LENGTH]


def is_valid_chat_image_id(image_id: object) -> bool:
    return isinstance(image_id, str) and bool(_CHAT_IMAGE_ID_PATTERN.fullmatch(image_id))


def chat_image_belongs_to(image_id: object, owner_key: str | None) -> bool:
    if not owner_key or not is_valid_chat_image_id(image_id):
        return False
    return hmac.compare_digest(str(image_id)[:_OWNER_DIGEST_LENGTH], _owner_digest(owner_key))


def resolve_chat_image_path(image_id: object, *, thumbnail: bool = False) -> str:
    """Resolve a validated image id to its file, refusing anything outside the root."""
    if not is_valid_chat_image_id(image_id):
        raise ValueError("Invalid chat image id.")
    root = os.path.realpath(get_chat_image_upload_root())
    filename = f"{image_id}{_THUMBNAIL_SUFFIX if thumbnail else _DISPLAY_SUFFIX}"
    candidate = os.path.realpath(os.path.join(root, filename))
    if os.path.commonpath((root, candidate)) != root:
        raise ValueError("Invalid chat image path.")
    return candidate


def save_chat_image(owner_key: str, display_bytes: bytes, thumbnail_bytes: bytes) -> str:
    """Persist both variants atomically and return the new owner-bound image id."""
    if not display_bytes or not thumbnail_bytes:
        raise ValueError("画像の変換結果が空です。")
    root = get_chat_image_upload_root()
    os.makedirs(root, exist_ok=True)
    image_id = f"{_owner_digest(owner_key)}{uuid4().hex}"
    display_path = resolve_chat_image_path(image_id)
    thumbnail_path = resolve_chat_image_path(image_id, thumbnail=True)
    try:
        _atomic_write(display_path, display_bytes)
        _atomic_write(thumbnail_path, thumbnail_bytes)
    except Exception:
        for path in (display_path, thumbnail_path):
            if os.path.isfile(path):
                os.remove(path)
        raise
    return image_id


def read_chat_image_bytes(image_id: str) -> bytes | None:
    """Return the display variant sent to the model, or None when it is gone."""
    try:
        with open(resolve_chat_image_path(image_id), "rb") as file_obj:
            return file_obj.read()
    except (OSError, ValueError):
        return None


def cleanup_unreferenced_chat_images(referenced_ids: Iterable[str], grace_seconds: int) -> int:
    """Delete image files older than the grace period that nothing references.

    参照は DB と一時ルームの両方から集めて渡す。猶予は、画像を保存してから発話を保存するまでの
    間に消さないためのもの。
    Callers pass references from both the database and temporary rooms; the grace covers the gap
    between storing an image and storing the message that references it.
    """
    root = get_chat_image_upload_root()
    if not os.path.isdir(root):
        return 0
    referenced = set(referenced_ids)
    cutoff = time.time() - grace_seconds
    deleted = 0
    for entry in os.scandir(root):
        if not entry.is_file():
            continue
        image_id = entry.name.removesuffix(_THUMBNAIL_SUFFIX).removesuffix(_DISPLAY_SUFFIX)
        if not is_valid_chat_image_id(image_id) or image_id in referenced:
            continue
        if entry.stat().st_mtime > cutoff:
            continue
        os.remove(entry.path)
        deleted += 1
    return deleted


def _atomic_write(destination: str, content: bytes) -> None:
    """Write a variant atomically so readers never observe a partial image."""
    fd, temporary_path = tempfile.mkstemp(prefix=".chat-image-", dir=os.path.dirname(destination))
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
