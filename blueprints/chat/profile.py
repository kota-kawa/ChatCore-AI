import logging
import os
import secrets

from fastapi import Request
from werkzeug.utils import secure_filename

from services.async_utils import run_blocking
from services.db import get_db_connection
from services.users import get_user_by_id
from services.web import BASE_DIR, jsonify, log_and_internal_server_error

from . import chat_bp

logger = logging.getLogger(__name__)

AVATAR_MAX_BYTES = 5 * 1024 * 1024
_AVATAR_CHUNK_SIZE = 1024 * 1024
_AVATAR_UPLOAD_DIR = os.path.join(BASE_DIR, "frontend", "public", "static", "uploads")
_ALLOWED_AVATAR_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_ALLOWED_AVATAR_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}
_AVATAR_FORMAT_TO_EXTENSIONS = {
    "jpeg": {".jpg", ".jpeg"},
    "png": {".png"},
    "gif": {".gif"},
    "webp": {".webp"},
}
_AVATAR_FORMAT_TO_CONTENT_TYPES = {
    "jpeg": {"image/jpeg"},
    "png": {"image/png"},
    "gif": {"image/gif"},
    "webp": {"image/webp"},
}
_AVATAR_FORMAT_TO_CANONICAL_EXTENSION = {
    "jpeg": ".jpg",
    "png": ".png",
    "gif": ".gif",
    "webp": ".webp",
}


def _detect_avatar_format(header: bytes) -> str | None:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return "gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    return None


def _normalize_content_type(raw_content_type) -> str:
    if not isinstance(raw_content_type, str):
        return ""
    return raw_content_type.split(";", 1)[0].strip().lower()


def _save_avatar_file(upload_dir, avatar_file_obj, original_filename, content_type):
    # 拡張子・Content-Type・マジックバイトを検証し、サイズ制限付きで保存する
    # Validate extension/content-type/signature and persist with a strict size cap.
    safe_filename = secure_filename(str(original_filename or ""))
    if not safe_filename:
        raise ValueError("画像ファイル名が不正です。")

    extension = os.path.splitext(safe_filename)[1].lower()
    if extension not in _ALLOWED_AVATAR_EXTENSIONS:
        raise ValueError("画像は JPG / PNG / GIF / WebP のいずれかを指定してください。")

    normalized_content_type = _normalize_content_type(content_type)
    if normalized_content_type and normalized_content_type not in _ALLOWED_AVATAR_CONTENT_TYPES:
        raise ValueError("画像ファイルのみアップロードできます。")

    if hasattr(avatar_file_obj, "seek"):
        avatar_file_obj.seek(0)
    header = avatar_file_obj.read(16)
    detected_format = _detect_avatar_format(header)
    if detected_format is None:
        raise ValueError("画像形式を判別できませんでした。")

    if extension not in _AVATAR_FORMAT_TO_EXTENSIONS[detected_format]:
        raise ValueError("ファイル拡張子と画像形式が一致しません。")

    if (
        normalized_content_type
        and normalized_content_type not in _AVATAR_FORMAT_TO_CONTENT_TYPES[detected_format]
    ):
        raise ValueError("Content-Typeと画像形式が一致しません。")

    if hasattr(avatar_file_obj, "seek"):
        avatar_file_obj.seek(0)

    os.makedirs(upload_dir, exist_ok=True)
    stored_filename = (
        f"avatar_{secrets.token_hex(16)}"
        f"{_AVATAR_FORMAT_TO_CANONICAL_EXTENSION[detected_format]}"
    )
    filepath = os.path.join(upload_dir, stored_filename)
    total_size = 0

    try:
        with open(filepath, "wb") as out_f:
            while True:
                chunk = avatar_file_obj.read(_AVATAR_CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > AVATAR_MAX_BYTES:
                    raise ValueError("画像サイズは5MB以下にしてください。")
                out_f.write(chunk)
    except Exception:
        if os.path.exists(filepath):
            os.remove(filepath)
        raise
    finally:
        if hasattr(avatar_file_obj, "seek"):
            try:
                avatar_file_obj.seek(0)
            except Exception:
                pass

    return f"/static/uploads/{stored_filename}"


def _update_user_profile(user_id, username, email, bio, avatar_url):
    # 入力されたプロフィール項目のみを users テーブルへ更新する
    # Update users table with submitted profile fields.
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE users
               SET username = %s,
                   email = %s,
                   bio = %s,
                   avatar_url = COALESCE(%s, avatar_url)
             WHERE id = %s
            """,
            (username, email, bio, avatar_url, user_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


# --- プロフィール取得 ---
# User profile read/update endpoint.
@chat_bp.api_route('/api/user/profile', methods=['GET', 'POST'], name="chat.user_profile")
async def user_profile(request: Request):
    """
    GET  : 自分のプロフィールを JSON で返す
    POST : フォーム / multipart で受け取ったプロフィールを更新する
    """
    if 'user_id' not in request.session:
        return jsonify({'error': 'ログインが必要です'}, status_code=401)
    user_id = request.session['user_id']

    # ---------- GET ----------
    # Return current profile data as JSON.
    if request.method == 'GET':
        user = await run_blocking(get_user_by_id, user_id)
        if not user:
            return jsonify({'error': 'ユーザーが存在しません'}, status_code=404)
        return jsonify({
            'username'  : user.get('username', ''),
            'email'     : user.get('email', ''),
            'bio'       : user.get('bio', ''),
            'avatar_url': user.get('avatar_url', '')
        })

    # ---------- POST ----------
    form = await request.form()
    username = (form.get('username') or '').strip()
    email = (form.get('email') or '').strip()
    bio = (form.get('bio') or '').strip()
    avatar_f = form.get('avatar')      # 画像ファイル (任意)
    # Optional avatar file from multipart form.

    if not username or not email:
        return jsonify({'error': 'ユーザー名とメールアドレスは必須です'}, status_code=400)

    # 画像アップロード (あれば)
    # Upload avatar file if one is provided.
    avatar_url = None
    if avatar_f and avatar_f.filename:
        try:
            avatar_url = await run_blocking(
                _save_avatar_file,
                _AVATAR_UPLOAD_DIR,
                avatar_f.file,
                avatar_f.filename,
                getattr(avatar_f, "content_type", ""),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}, status_code=400)
        except Exception:
            return log_and_internal_server_error(
                logger,
                "Failed to store uploaded avatar image.",
            )

    # DB 更新
    # Persist profile updates to database.
    try:
        await run_blocking(_update_user_profile, user_id, username, email, bio, avatar_url)
        return jsonify({
            'message': 'プロフィールを更新しました',
            'avatar_url': avatar_url         # 新しい画像 URL（ない場合は null）
            # Newly uploaded avatar URL (null when unchanged).
        })
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to update user profile.",
        )
