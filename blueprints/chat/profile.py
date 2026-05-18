import logging
import os
import secrets
import time

from fastapi import Depends, Request
from werkzeug.utils import secure_filename

from services.api_errors import DEFAULT_RETRY_AFTER_SECONDS, parse_retry_after_seconds
from services.async_utils import run_blocking
from services.auth_limits import (
    AuthLimitService,
    consume_auth_email_send_limits,
    get_auth_limit_service,
)
from services.db import get_db_connection
from services.email_service import send_email
from services.llm_daily_limit import (
    LlmDailyLimitService,
    consume_auth_email_daily_quota,
    get_llm_daily_limit_service,
    get_seconds_until_daily_reset,
)
from services.request_models import EmailChangeConfirmRequest, EmailChangeRequest
from services.security import constant_time_compare, generate_verification_code
from services.users import get_user_by_email, get_user_by_id
from services.web import (
    BASE_DIR,
    jsonify,
    jsonify_rate_limited,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

from . import chat_bp

EMAIL_CHANGE_CODE_TTL_SECONDS = 600
EMAIL_CHANGE_CODE_MAX_ATTEMPTS = 5
EMAIL_CHANGE_SESSION_KEY = "email_change"
EMAIL_CHANGE_STAGE_CURRENT = "current_email"
EMAIL_CHANGE_STAGE_NEW = "new_email"

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


def _update_user_profile(user_id, username, email, bio, avatar_url, llm_profile_context):
    # Update only non-identity profile fields. The email column is intentionally
    # excluded — changing the email is privileged and must go through the
    # verification flow at /api/user/email (request_change + confirm_change),
    # otherwise an attacker holding any authenticated session could rewrite
    # the email and intercept future verification mails. The `email` argument
    # is kept in the signature for backwards compatibility with the test
    # fixtures but is no longer written to the database.
    _ = email  # intentionally ignored; see docstring above
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE users
                   SET username = %s,
                       bio = %s,
                       llm_profile_context = %s,
                       avatar_url = COALESCE(%s, avatar_url)
                 WHERE id = %s
                """,
                (username, bio, llm_profile_context, avatar_url, user_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


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
            'avatar_url': user.get('avatar_url', ''),
            'llm_profile_context': user.get('llm_profile_context'),
        })

    # ---------- POST ----------
    form = await request.form()
    username = (form.get('username') or '').strip()
    submitted_email = (form.get('email') or '').strip()
    bio = (form.get('bio') or '').strip()
    llm_profile_context = (form.get('llm_profile_context') or '').strip()
    avatar_f = form.get('avatar')      # 画像ファイル (任意)
    # Optional avatar file from multipart form.

    if not username:
        return jsonify({'error': 'ユーザー名は必須です'}, status_code=400)

    # Reject attempts to change the email through the generic profile-update
    # endpoint. Email changes must go through the verification flow so an
    # attacker holding a single authenticated session cannot retarget
    # verification mails to an address they control.
    current_user = await run_blocking(get_user_by_id, user_id)
    current_email = (current_user or {}).get('email', '') if current_user else ''
    if submitted_email and submitted_email.lower() != (current_email or '').lower():
        return jsonify(
            {
                'error': (
                    'メールアドレスを変更するには、新しいアドレス宛に送信される'
                    '認証コードによる確認が必要です。設定画面の「メールアドレス変更」'
                    'からお手続きください。'
                ),
            },
            status_code=400,
        )
    email = current_email

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
        await run_blocking(
            _update_user_profile,
            user_id,
            username,
            email,
            bio,
            avatar_url,
            llm_profile_context,
        )
        return jsonify({
            'message': 'プロフィールを更新しました',
            'avatar_url': avatar_url,        # 新しい画像 URL（ない場合は null）
            'llm_profile_context': llm_profile_context,
            # Newly uploaded avatar URL (null when unchanged).
        })
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to update user profile.",
        )


def _clear_email_change_session(session: dict) -> None:
    session.pop(EMAIL_CHANGE_SESSION_KEY, None)


async def _send_email_change_code(
    *,
    request: Request,
    to_email: str,
    subject: str,
    body_text: str,
    auth_limit_service: AuthLimitService | None,
    llm_daily_limit_service: LlmDailyLimitService | None,
) -> str | None:
    allowed, limit_error = consume_auth_email_send_limits(
        request,
        to_email,
        service=auth_limit_service,
    )
    if not allowed:
        return limit_error or '試行回数が多すぎます。時間をおいて再試行してください。'

    can_send_email, _, daily_limit = await run_blocking(
        consume_auth_email_daily_quota,
        service=llm_daily_limit_service,
    )
    if not can_send_email:
        return (
            f'本日の認証メール送信上限（全ユーザー合計 {daily_limit} 件）に達しました。'
            '日付が変わってから再度お試しください。'
        )

    await run_blocking(
        send_email,
        to_address=to_email,
        subject=subject,
        body_text=body_text,
    )
    return None


def _commit_email_change(user_id: int, new_email: str) -> bool:
    # Atomically rewrite users.email after the new address has been verified.
    # Returns False if some other account claimed the address between the
    # request and the confirmation step, so the caller can report a clear
    # error instead of leaving the row in an inconsistent state.
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id FROM users WHERE LOWER(email) = LOWER(%s)
                """,
                (new_email,),
            )
            row = cursor.fetchone()
            if row and row[0] != user_id:
                conn.rollback()
                return False
            cursor.execute(
                """
                UPDATE users SET email = %s WHERE id = %s
                """,
                (new_email, user_id),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


@chat_bp.post('/api/user/email/request_change', name='chat.request_email_change')
async def request_email_change(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
    llm_daily_limit_service: LlmDailyLimitService | None = Depends(get_llm_daily_limit_service),
):
    if 'user_id' not in request.session:
        return jsonify({'error': 'ログインが必要です'}, status_code=401)
    user_id = request.session['user_id']

    data, error_response = await require_json_dict(request, status='fail')
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        EmailChangeRequest,
        error_message='メールアドレスの形式が正しくありません',
        status='fail',
    )
    if validation_error is not None:
        return validation_error

    new_email = payload.new_email
    user = await run_blocking(get_user_by_id, user_id)
    if not user:
        return jsonify({'error': 'ユーザーが存在しません'}, status_code=404)

    current_email = (user.get('email') or '').lower()
    if new_email == current_email:
        return jsonify(
            {'error': '現在のメールアドレスと同じです'},
            status_code=400,
        )

    existing = await run_blocking(get_user_by_email, new_email)
    if existing and existing.get('id') != user_id:
        # Don't leak existence: keep the message generic but block the change.
        return jsonify(
            {'error': 'このメールアドレスは利用できません'},
            status_code=400,
        )

    code = generate_verification_code()
    request.session[EMAIL_CHANGE_SESSION_KEY] = {
        'stage': EMAIL_CHANGE_STAGE_CURRENT,
        'code': code,
        'current_email': current_email,
        'new_email': new_email,
        'issued_at': int(time.time()),
        'attempts': 0,
    }

    subject = 'AIチャットサービス: メールアドレス変更の確認'
    body_text = (
        'メールアドレス変更のリクエストを受け付けました。\n'
        'まず現在のメールアドレスの確認が必要です。以下の確認コードを設定画面に入力してください。\n\n'
        f'確認コード: {code}\n\n'
        f'変更先メールアドレス: {new_email}\n\n'
        'この確認後、変更先メールアドレスにも確認コードを送信します。\n'
        '心当たりがない場合はこのメールを無視してください。'
    )
    try:
        send_error = await _send_email_change_code(
            request=request,
            to_email=current_email,
            subject=subject,
            body_text=body_text,
            auth_limit_service=auth_limit_service,
            llm_daily_limit_service=llm_daily_limit_service,
        )
        if send_error:
            _clear_email_change_session(request.session)
            if '本日の認証メール送信上限' in send_error:
                return jsonify_rate_limited(
                    send_error,
                    retry_after=get_seconds_until_daily_reset(),
                    status='fail',
                )
            return jsonify_rate_limited(
                send_error,
                retry_after=parse_retry_after_seconds(
                    send_error,
                    default=DEFAULT_RETRY_AFTER_SECONDS,
                ),
                status='fail',
            )
        return jsonify({'status': 'success'})
    except Exception:
        _clear_email_change_session(request.session)
        return log_and_internal_server_error(
            logger,
            'Failed to send email-change verification code.',
            status='fail',
        )


@chat_bp.post('/api/user/email/confirm_change', name='chat.confirm_email_change')
async def confirm_email_change(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
    llm_daily_limit_service: LlmDailyLimitService | None = Depends(get_llm_daily_limit_service),
):
    if 'user_id' not in request.session:
        return jsonify({'error': 'ログインが必要です'}, status_code=401)
    user_id = request.session['user_id']

    data, error_response = await require_json_dict(request, status='fail')
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        EmailChangeConfirmRequest,
        error_message='確認コードを入力してください',
        status='fail',
    )
    if validation_error is not None:
        return validation_error

    state = request.session.get(EMAIL_CHANGE_SESSION_KEY)
    if not isinstance(state, dict) or not state.get('code') or not state.get('new_email'):
        return jsonify(
            {'status': 'fail', 'error': 'メールアドレス変更のセッション情報がありません。最初からやり直してください'},
            status_code=400,
        )

    issued_at = int(state.get('issued_at') or 0)
    attempts = int(state.get('attempts') or 0)

    if issued_at <= 0 or int(time.time()) - issued_at > EMAIL_CHANGE_CODE_TTL_SECONDS:
        _clear_email_change_session(request.session)
        return jsonify(
            {'status': 'fail', 'error': '確認コードの有効期限が切れています'},
            status_code=400,
        )

    if attempts >= EMAIL_CHANGE_CODE_MAX_ATTEMPTS:
        _clear_email_change_session(request.session)
        return jsonify(
            {'status': 'fail', 'error': '確認コードの試行回数が上限に達しました'},
            status_code=429,
        )

    expected_code = str(state.get('code') or '')
    submitted_code = str(payload.auth_code or '')
    if not constant_time_compare(submitted_code, expected_code):
        attempts += 1
        state['attempts'] = attempts
        request.session[EMAIL_CHANGE_SESSION_KEY] = state
        if attempts >= EMAIL_CHANGE_CODE_MAX_ATTEMPTS:
            _clear_email_change_session(request.session)
            return jsonify(
                {'status': 'fail', 'error': '確認コードの試行回数が上限に達しました'},
                status_code=429,
            )
        return jsonify(
            {'status': 'fail', 'error': '確認コードが一致しません'},
            status_code=400,
        )

    stage = str(state.get('stage') or EMAIL_CHANGE_STAGE_NEW)
    new_email = state['new_email']
    if stage == EMAIL_CHANGE_STAGE_CURRENT:
        code = generate_verification_code()
        state.update(
            {
                'stage': EMAIL_CHANGE_STAGE_NEW,
                'code': code,
                'issued_at': int(time.time()),
                'attempts': 0,
            }
        )
        request.session[EMAIL_CHANGE_SESSION_KEY] = state

        subject = 'AIチャットサービス: メールアドレス変更の確認'
        body_text = (
            '変更先メールアドレスの確認が必要です。\n'
            '以下の確認コードを設定画面に入力すると、メールアドレスの変更が完了します。\n\n'
            f'確認コード: {code}\n\n'
            '心当たりがない場合はこのメールを無視してください。'
        )
        try:
            send_error = await _send_email_change_code(
                request=request,
                to_email=new_email,
                subject=subject,
                body_text=body_text,
                auth_limit_service=auth_limit_service,
                llm_daily_limit_service=llm_daily_limit_service,
            )
        except Exception:
            _clear_email_change_session(request.session)
            return log_and_internal_server_error(
                logger,
                'Failed to send new-address email-change verification code.',
                status='fail',
            )

        if send_error:
            _clear_email_change_session(request.session)
            if '本日の認証メール送信上限' in send_error:
                return jsonify_rate_limited(
                    send_error,
                    retry_after=get_seconds_until_daily_reset(),
                    status='fail',
                )
            return jsonify_rate_limited(
                send_error,
                retry_after=parse_retry_after_seconds(
                    send_error,
                    default=DEFAULT_RETRY_AFTER_SECONDS,
                ),
                status='fail',
            )

        return jsonify(
            {
                'status': 'success',
                'stage': EMAIL_CHANGE_STAGE_NEW,
                'message': '変更先メールアドレスに確認コードを送信しました',
            }
        )

    if stage != EMAIL_CHANGE_STAGE_NEW:
        _clear_email_change_session(request.session)
        return jsonify(
            {'status': 'fail', 'error': 'メールアドレス変更の状態が不正です。最初からやり直してください'},
            status_code=400,
        )

    try:
        committed = await run_blocking(_commit_email_change, user_id, new_email)
    except Exception:
        _clear_email_change_session(request.session)
        return log_and_internal_server_error(
            logger,
            'Failed to commit email-change update.',
            status='fail',
        )

    _clear_email_change_session(request.session)
    if not committed:
        return jsonify(
            {'status': 'fail', 'error': 'このメールアドレスは利用できません'},
            status_code=409,
        )

    request.session['user_email'] = new_email
    return jsonify({'status': 'success', 'email': new_email})
