"""Storage layout and public URL shape for uploaded user avatars.

アバター画像は Next.js が配信する `frontend/public/static/uploads/` に置き、
`/static/uploads/<filename>` として公開する。保存先・公開URLの接頭辞・既定
アイコンを1箇所に集約し、`services/prompt_attachment_storage.py` と同じ形で
URL生成の入口を1つに保つ。
"""

from __future__ import annotations

import os

from .web_constants import BASE_DIR

# アップロードされたアバター画像の保存先ディレクトリ
# Directory that stores uploaded avatar images.
AVATAR_UPLOAD_DIR = os.path.join(BASE_DIR, "frontend", "public", "static", "uploads")

# アバター画像の公開URL接頭辞
# Public URL prefix serving the uploaded avatar images.
AVATAR_PUBLIC_URL_PREFIX = "/static/uploads"

# アバター未設定のユーザーに使う既定アイコン
# Default icon used when a user has no avatar of their own.
DEFAULT_AVATAR_URL = "/static/user-icon.png"

# DB カラムに保存できるアバターURLの最大長
# Maximum avatar URL length the database column accepts.
AVATAR_URL_MAX_LENGTH = 255


def build_avatar_public_url(filename: object) -> str:
    """Build the public URL for a stored avatar image."""
    safe_filename = str(filename or "").strip()
    if not safe_filename:
        raise ValueError("An avatar filename is required.")
    # 生成済みファイル名しか渡らない想定だが、別パスへ逸れるURLは作らせない
    # Only generated filenames reach here; still refuse anything but one segment.
    if any(character in safe_filename for character in "/\\?#"):
        raise ValueError("An avatar filename must be a single URL path segment.")
    return f"{AVATAR_PUBLIC_URL_PREFIX}/{safe_filename}"


def normalize_avatar_url(avatar_url: str | None) -> str:
    """Return a storable avatar URL, falling back to the default icon."""
    normalized = (avatar_url or "").strip()
    if not normalized or len(normalized) > AVATAR_URL_MAX_LENGTH:
        return DEFAULT_AVATAR_URL
    return normalized
