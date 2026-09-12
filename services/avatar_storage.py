"""Storage layout and public URL shape for uploaded user avatars.

アバター画像はアプリ（FastAPI）が所有する永続ボリューム配下に置き、
``/api/user/avatars/<filename>`` としてバックエンドから配信する。以前は
``frontend/public/static/uploads`` へ書いて ``/static/uploads/<filename>`` を
返していたが、その URL は nginx の backend location に一致せず frontend
コンテナへ流れるため 404 になり、保存先もボリュームではなかったため再デプロイ
で消えていた。保存先・公開URLの接頭辞・既定アイコンを1箇所に集約する方針は
``services/prompt_attachment_storage.py`` と同じで、旧形式の URL も
``normalize_avatar_url`` が新形式へ読み替える。

Avatars live under an app-owned persistent volume and are served by the backend
at ``/api/user/avatars/<filename>``. The former ``/static/uploads`` prefix never
reached the backend through nginx and was not backed by a volume.
"""

from __future__ import annotations

import os
import re
import time
from urllib.parse import urlsplit

from .web_constants import BASE_DIR

# アバターの保存先を上書きする環境変数名
# Environment variable overriding the avatar storage directory.
AVATAR_UPLOAD_ROOT_ENV = "AVATAR_UPLOAD_DIR"

# アバター画像の公開URL接頭辞（nginx の backend location に一致させること）
# Public URL prefix for avatars; it must match the nginx backend location regex.
AVATAR_PUBLIC_URL_PREFIX = "/api/user/avatars"

# バックエンドが配信していなかった旧公開URL接頭辞
# Former public URL prefix that the backend never served.
LEGACY_AVATAR_URL_PREFIX = "/static/uploads"

# アバター未設定のユーザーに使う既定アイコン（frontend が配信する静的アセット）
# Default icon for users without an avatar; served by the frontend as a static asset.
DEFAULT_AVATAR_URL = "/static/user-icon.png"

# DB カラムに保存できるアバターURLの最大長
# Maximum avatar URL length the database column accepts.
AVATAR_URL_MAX_LENGTH = 255

# 参照されていないアバターを削除するまでの猶予時間（秒）
# Grace period before an unreferenced avatar file becomes deletable.
AVATAR_ORPHAN_GRACE_SECONDS = 60 * 60

_DEFAULT_AVATAR_UPLOAD_ROOT = os.path.join(BASE_DIR, "data", "uploads", "avatars")
_SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_IMAGE_CONTENT_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def get_avatar_upload_root() -> str:
    """Return the configured absolute storage directory for avatar images."""
    configured = str(os.getenv(AVATAR_UPLOAD_ROOT_ENV, "") or "").strip()
    if not configured:
        return os.path.abspath(_DEFAULT_AVATAR_UPLOAD_ROOT)
    if not os.path.isabs(configured):
        configured = os.path.join(BASE_DIR, configured)
    return os.path.abspath(configured)


def get_legacy_avatar_upload_root() -> str:
    """Return the former frontend-served directory kept only for reads."""
    return os.path.abspath(os.path.join(BASE_DIR, "frontend", "public", "static", "uploads"))


def validate_avatar_filename(filename: object) -> str:
    """Validate a single avatar filename before resolving it below the upload root."""
    value = str(filename or "").strip()
    if (
        not value
        or not _SAFE_FILENAME_PATTERN.fullmatch(value)
        or os.path.basename(value) != value
        or os.path.splitext(value)[1].lower() not in _IMAGE_CONTENT_TYPES
    ):
        raise ValueError("Invalid avatar filename.")
    return value


def _resolve_below(root: str, filename: object, message: str) -> str:
    safe_filename = validate_avatar_filename(filename)
    resolved_root = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(resolved_root, safe_filename))
    if os.path.commonpath((resolved_root, candidate)) != resolved_root:
        raise ValueError(message)
    return candidate


def resolve_avatar_path(filename: object) -> str:
    """Resolve a validated filename while preventing traversal and symlink escapes."""
    return _resolve_below(get_avatar_upload_root(), filename, "Invalid avatar path.")


def resolve_legacy_avatar_path(filename: object) -> str:
    """Resolve a validated filename below the former frontend/public location."""
    return _resolve_below(get_legacy_avatar_upload_root(), filename, "Invalid legacy avatar path.")


def avatar_content_type(filename: object) -> str:
    """Return a deterministic image Content-Type from a validated extension."""
    safe_filename = validate_avatar_filename(filename)
    return _IMAGE_CONTENT_TYPES[os.path.splitext(safe_filename)[1].lower()]


def build_avatar_public_url(filename: object) -> str:
    """Build the backend-served public URL for a stored avatar image."""
    safe_filename = validate_avatar_filename(filename)
    return f"{AVATAR_PUBLIC_URL_PREFIX}/{safe_filename}"


def avatar_filename_from_url(url: object) -> str | None:
    """Extract a safe filename from either the current or legacy relative URL."""
    raw_url = str(url or "").strip()
    if not raw_url:
        return None
    parsed_url = urlsplit(raw_url)
    if parsed_url.scheme or parsed_url.netloc:
        return None
    path = parsed_url.path
    for prefix in (AVATAR_PUBLIC_URL_PREFIX, LEGACY_AVATAR_URL_PREFIX):
        expected_prefix = f"{prefix}/"
        if not path.startswith(expected_prefix):
            continue
        try:
            return validate_avatar_filename(path[len(expected_prefix) :])
        except ValueError:
            return None
    return None


def normalize_avatar_url(avatar_url: str | None) -> str:
    """Return a storable avatar URL, rewriting the legacy prefix to the served one.

    旧 ``/static/uploads/<file>`` はバックエンドに届かないため、読み書きの両方で
    現行の接頭辞へ読み替える。判別できない値は既定アイコンへ落とす。
    """
    normalized = (avatar_url or "").strip()
    if not normalized or len(normalized) > AVATAR_URL_MAX_LENGTH:
        return DEFAULT_AVATAR_URL
    filename = avatar_filename_from_url(normalized)
    if filename is not None:
        return build_avatar_public_url(filename)
    return normalized


def cleanup_unreferenced_avatars(avatar_urls: list[str]) -> int:
    """Delete stored avatars no active user row still references.

    アップロードのたびに新しいファイル名を作るため、古いファイルが残り続ける。
    プロンプト添付と同じく DB を正とした照合で孤児を削除する。
    """
    referenced = {
        filename
        for avatar_url in avatar_urls
        for filename in (avatar_filename_from_url(avatar_url),)
        if filename is not None
    }
    root = get_avatar_upload_root()
    if not os.path.isdir(root):
        return 0
    cutoff = time.time() - AVATAR_ORPHAN_GRACE_SECONDS
    deleted = 0
    for entry in os.scandir(root):
        if not entry.is_file() or entry.name in referenced:
            continue
        try:
            validate_avatar_filename(entry.name)
        except ValueError:
            continue
        if entry.stat().st_mtime > cutoff:
            continue
        os.remove(entry.path)
        deleted += 1
    return deleted
