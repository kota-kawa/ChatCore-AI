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

# メールアドレス変更用認証コードの有効期間（秒）
# Time-To-Live (seconds) for email change verification code.
EMAIL_CHANGE_CODE_TTL_SECONDS = 600

# メールアドレス変更用認証コードの最大試行回数
# Maximum allowed verification attempts for email change.
EMAIL_CHANGE_CODE_MAX_ATTEMPTS = 5

# セッション内でメールアドレス変更情報を保持するキー名
# Session key for storing email change state data.
EMAIL_CHANGE_SESSION_KEY = "email_change"

# 現在のメールアドレス確認ステージ名
# Stage name representing verification of the current email address.
EMAIL_CHANGE_STAGE_CURRENT = "current_email"

# 新しいメールアドレス確認ステージ名
# Stage name representing verification of the new email address.
EMAIL_CHANGE_STAGE_NEW = "new_email"

logger = logging.getLogger(__name__)

# アバター画像の最大許容サイズ（5MB）
# Maximum allowed bytes for an avatar image file (5MB).
AVATAR_MAX_BYTES = 5 * 1024 * 1024

# アバター画像を読み書きする際のバッファチャンクサイズ（1MB）
# Chunk size (1MB) used when reading and writing the avatar file in bytes.
_AVATAR_CHUNK_SIZE = 1024 * 1024

# アバター画像のアップロード先ディレクトリ
# Upload destination directory for avatar images.
_AVATAR_UPLOAD_DIR = os.path.join(BASE_DIR, "frontend", "public", "static", "uploads")

# アバター画像として許可される拡張子のセット
# Set of allowed file extensions for avatar images.
_ALLOWED_AVATAR_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# アバター画像として許可されるContent-Typeのセット
# Set of allowed Content-Type header values for avatar images.
_ALLOWED_AVATAR_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}

# 画像形式から拡張子への対応マップ
# Mapping from detected format to its valid extensions.
_AVATAR_FORMAT_TO_EXTENSIONS = {
    "jpeg": {".jpg", ".jpeg"},
    "png": {".png"},
    "gif": {".gif"},
    "webp": {".webp"},
}

# 画像形式からContent-Typeへの対応マップ
# Mapping from detected format to its valid Content-Types.
_AVATAR_FORMAT_TO_CONTENT_TYPES = {
    "jpeg": {"image/jpeg"},
    "png": {"image/png"},
    "gif": {"image/gif"},
    "webp": {"image/webp"},
}

# 画像形式から正規拡張子への対応マップ
# Mapping from detected format to its canonical extension.
_AVATAR_FORMAT_TO_CANONICAL_EXTENSION = {
    "jpeg": ".jpg",
    "png": ".png",
    "gif": ".gif",
    "webp": ".webp",
}


# アバター画像のマジックバイト（シグネチャ）から画像形式を特定する関数
# Detect the avatar image format (PNG, JPEG, GIF, or WEBP) based on file magic bytes.
def _detect_avatar_format(header: bytes) -> str | None:
    """
    マジックバイト（ファイルの先頭バイト）を解析して、画像形式を特定します。
    Analyzes the magic bytes (file signature) to detect the image format.
    """
    # PNGのヘッダーを判定
    # Detect PNG header
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    # JPEGのヘッダーを判定
    # Detect JPEG header
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    # GIFのヘッダーを判定
    # Detect GIF header
    if header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return "gif"
    # WEBPのヘッダーを判定
    # Detect WEBP header
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    # 判定不能な場合
    # Unknown format
    return None


# HTTPヘッダーのContent-Typeを正規化（パラメータ除去・小文字化）する関数
# Normalize the raw Content-Type header value by stripping parameters and converting to lowercase.
def _normalize_content_type(raw_content_type) -> str:
    """
    HTTPヘッダーのContent-Typeからパラメータ部分を削り、小文字に正規化します。
    Strips parameters from the HTTP Content-Type header and normalizes it to lowercase.
    """
    if not isinstance(raw_content_type, str):
        return ""
    # セミコロン以降のパラメータを切り離して、前後の空白を除去し、小文字化
    # Split the parameter part after the semicolon, strip whitespace, and lower-case it.
    return raw_content_type.split(";", 1)[0].strip().lower()


# アップロードされたアバター画像ファイルを検証してディスクに保存する関数
# Validate and save the uploaded avatar image file to disk, enforcing size/type constraints.
def _save_avatar_file(upload_dir, avatar_file_obj, original_filename, content_type):
    """
    アップロードされたアバター画像を検証し、問題なければ一意のファイル名で保存します。
    Validates the uploaded avatar image and saves it with a unique filename if valid.
    """
    # 拡張子・Content-Type・マジックバイトを検証し、サイズ制限付きで保存する
    # Validate extension/content-type/signature and persist with a strict size cap.
    
    # ファイル名を安全な形に変換
    # Sanitize the filename
    safe_filename = secure_filename(str(original_filename or ""))
    if not safe_filename:
        raise ValueError("画像ファイル名が不正です。")

    # 拡張子を検証
    # Validate file extension
    extension = os.path.splitext(safe_filename)[1].lower()
    if extension not in _ALLOWED_AVATAR_EXTENSIONS:
        raise ValueError("画像は JPG / PNG / GIF / WebP のいずれかを指定してください。")

    # Content-Typeを検証
    # Validate content-type
    normalized_content_type = _normalize_content_type(content_type)
    if normalized_content_type and normalized_content_type not in _ALLOWED_AVATAR_CONTENT_TYPES:
        raise ValueError("画像ファイルのみアップロードできます。")

    # ファイルポインタを先頭に戻す（可能な場合）
    # Rewind the file pointer if possible
    if hasattr(avatar_file_obj, "seek"):
        avatar_file_obj.seek(0)
        
    # 先頭16バイトを読み取ってマジックバイトから画像形式を特定
    # Read the first 16 bytes and detect the image format from magic bytes
    header = avatar_file_obj.read(16)
    detected_format = _detect_avatar_format(header)
    if detected_format is None:
        raise ValueError("画像形式を判別できませんでした。")

    # 拡張子と画像形式が合致しているか検証
    # Ensure extension matches the detected image format
    if extension not in _AVATAR_FORMAT_TO_EXTENSIONS[detected_format]:
        raise ValueError("ファイル拡張子と画像形式が一致しません。")

    # Content-Typeと画像形式が合致しているか検証
    # Ensure Content-Type matches the detected image format
    if (
        normalized_content_type
        and normalized_content_type not in _AVATAR_FORMAT_TO_CONTENT_TYPES[detected_format]
    ):
        raise ValueError("Content-Typeと画像形式が一致しません。")

    # 読み取り用にポインタを再度先頭に戻す
    # Rewind the pointer again to start saving the file from the beginning
    if hasattr(avatar_file_obj, "seek"):
        avatar_file_obj.seek(0)

    # アップロードディレクトリが存在しない場合は作成
    # Create the upload directory if it does not exist
    os.makedirs(upload_dir, exist_ok=True)
    
    # 保存用の一意なファイル名を生成
    # Generate a unique stored filename
    stored_filename = (
        f"avatar_{secrets.token_hex(16)}"
        f"{_AVATAR_FORMAT_TO_CANONICAL_EXTENSION[detected_format]}"
    )
    filepath = os.path.join(upload_dir, stored_filename)
    total_size = 0

    try:
        # ファイルをチャンク単位で書き込み、サイズ上限を超えないか監視
        # Write the file in chunks and monitor that size does not exceed the limit
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
        # 書き込み中に例外が発生した場合は、中途半端なファイルを削除
        # Clean up any partially written file if an exception occurs
        if os.path.exists(filepath):
            os.remove(filepath)
        raise
    finally:
        # ポインタを先頭に戻しておく
        # Rewind the file pointer for subsequent operations
        if hasattr(avatar_file_obj, "seek"):
            try:
                avatar_file_obj.seek(0)
            except Exception:
                pass

    # 保存されたアバター画像のURLパスを返す
    # Return the URL path to the saved avatar image
    return f"/static/uploads/{stored_filename}"


# ユーザーのプロフィール情報（メールアドレスを除く）をデータベースに保存する関数
# Persist updated user profile fields (excluding email) to the database.
def _update_user_profile(user_id, username, email, bio, avatar_url, llm_profile_context):
    """
    ユーザーのプロフィール情報（ユーザー名、自己紹介、LLM設定、アバターURL）をDBで更新します。
    Updates user profile details (username, bio, LLM context, avatar URL) in the database.
    """
    # Update only non-identity profile fields. The email column is intentionally
    # excluded — changing the email is privileged and must go through the
    # verification flow at /api/user/email (request_change + confirm_change),
    # otherwise an attacker holding any authenticated session could rewrite
    # the email and intercept future verification mails. The `email` argument
    # is kept in the signature for backwards compatibility with the test
    # fixtures but is no longer written to the database.
    _ = email  # intentionally ignored; see docstring above
    
    # データベースに接続して更新クエリを実行
    # Connect to the database and run the update query
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
            # コミットして変更を確定
            # Commit to finalize updates
            conn.commit()
        except Exception:
            # エラー発生時はロールバック
            # Rollback on database errors
            conn.rollback()
            raise
        finally:
            # カーソルを閉じる
            # Close database cursor
            cursor.close()


# --- プロフィール取得 ---
# User profile read/update endpoint.
# プロフィール情報の取得・更新を行うAPIエンドポイント
# API endpoint to retrieve or update user profile information.
@chat_bp.api_route('/api/user/profile', methods=['GET', 'POST'], name="chat.user_profile")
async def user_profile(request: Request):
    """
    GET: ユーザーのプロフィール情報を取得します。
    GET: Retrieves the user's profile details.
    
    POST: ユーザーのプロフィール情報（ユーザー名、自己紹介、アバター画像等）を更新します。
    POST: Updates the user's profile details (username, bio, avatar, etc.).
    """
    # ユーザーがログインしているかセッションをチェック
    # Validate user is authenticated by checking the session
    if 'user_id' not in request.session:
        return jsonify({'error': 'ログインが必要です'}, status_code=401)
    user_id = request.session['user_id']

    # ---------- GET ----------
    # Return current profile data as JSON.
    if request.method == 'GET':
        # ユーザー情報をDBから取得
        # Retrieve user details from the database
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
    # マルチパートフォームからの入力を取得
    # Extract input fields from the multipart form
    form = await request.form()
    username = (form.get('username') or '').strip()
    submitted_email = (form.get('email') or '').strip()
    bio = (form.get('bio') or '').strip()
    llm_profile_context = (form.get('llm_profile_context') or '').strip()
    avatar_f = form.get('avatar')      # 画像ファイル (任意)
    # Optional avatar file from multipart form.

    # ユーザー名の必須チェック
    # Ensure username is provided
    if not username:
        return jsonify({'error': 'ユーザー名は必須です'}, status_code=400)

    # 一般のプロフィール更新ルート経由でのメールアドレス変更試行を拒否
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

    # 画像がアップロードされている場合はバリデーションと保存処理を実施
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

    # DBにプロフィール更新情報を永続化
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


# セッションからメールアドレス変更関連の一時データを削除する関数
# Clear email change related state data from the user's session.
def _clear_email_change_session(session: dict) -> None:
    """
    セッション内にあるメールアドレス変更関連のデータをクリアします。
    Removes email change related details from the user session.
    """
    session.pop(EMAIL_CHANGE_SESSION_KEY, None)


# メールアドレス変更用認証コード付きの確認メールを送信する非同期関数
# Asynchronously send verification code email for email change request, enforcing rate limits.
async def _send_email_change_code(
    *,
    request: Request,
    to_email: str,
    subject: str,
    body_text: str,
    auth_limit_service: AuthLimitService | None,
    llm_daily_limit_service: LlmDailyLimitService | None,
) -> str | None:
    """
    レート制限をチェックしつつ、メールアドレス変更のための確認メールを送信します。
    Sends a verification email for modifying the email address, enforcing rate/quota limits.
    """
    # IP/メール送信数に応じた送信制限（短時間あたりの試行制限）の確認
    # Check short-term rate limits on email sending per IP/email
    allowed, limit_error = consume_auth_email_send_limits(
        request,
        to_email,
        service=auth_limit_service,
    )
    if not allowed:
        return limit_error or '試行回数が多すぎます。時間をおいて再試行してください。'

    # 1日の全体的な送信クォータ制限の確認
    # Check global daily quota limits
    can_send_email, _, daily_limit = await run_blocking(
        consume_auth_email_daily_quota,
        service=llm_daily_limit_service,
    )
    if not can_send_email:
        return (
            f'本日の認証メール送信上限（全ユーザー合計 {daily_limit} 件）に達しました。'
            '日付が変わってから再度お試しください。'
        )

    # メール送信処理を実行
    # Perform email dispatching
    await run_blocking(
        send_email,
        to_address=to_email,
        subject=subject,
        body_text=body_text,
    )
    return None


# 認証完了後に新しいメールアドレスをDBに反映する関数
# Atomically update users.email in the database after the verification steps.
def _commit_email_change(user_id: int, new_email: str) -> bool:
    """
    DBに対して、新しいメールアドレスを一意性の重複衝突に注意しながら反映します。
    Updates the email address in the database, checking for collisions first.
    """
    # Atomically rewrite users.email after the new address has been verified.
    # Returns False if some other account claimed the address between the
    # request and the confirmation step, so the caller can report a clear
    # error instead of leaving the row in an inconsistent state.
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            # 既に別アカウントで同じメールアドレスが登録されていないか確認
            # Check if another account has already claimed the new email
            cursor.execute(
                """
                SELECT id FROM users WHERE LOWER(email) = LOWER(%s)
                """,
                (new_email,),
            )
            row = cursor.fetchone()
            if row and row[0] != user_id:
                # 重複した場合はロールバックして失敗とする
                # Rollback and return False if duplicate email exists
                conn.rollback()
                return False
            
            # メールアドレスを更新
            # Perform the database update for the email
            cursor.execute(
                """
                UPDATE users SET email = %s WHERE id = %s
                """,
                (new_email, user_id),
            )
            conn.commit()
            return True
        except Exception:
            # 例外時はロールバック
            # Rollback on database exception
            conn.rollback()
            raise
        finally:
            cursor.close()


# メールアドレス変更手続きを開始し、現在のメールアドレス宛に認証コードを送信するAPIエンドポイント
# API endpoint to initiate email change request and send verification code to current address.
@chat_bp.post('/api/user/email/request_change', name='chat.request_email_change')
async def request_email_change(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
    llm_daily_limit_service: LlmDailyLimitService | None = Depends(get_llm_daily_limit_service),
):
    """
    メールアドレスの変更リクエストを受け付け、現在のメールアドレスへ確認コードを送信します。
    Initiates an email change request and dispatches a verification code to the current email address.
    """
    # ユーザーの認証チェック
    # Validate session authentication
    if 'user_id' not in request.session:
        return jsonify({'error': 'ログインが必要です'}, status_code=401)
    user_id = request.session['user_id']

    # リクエストデータがJSON形式であることを保証
    # Ensure request payload is a dictionary in JSON format
    data, error_response = await require_json_dict(request, status='fail')
    if error_response is not None:
        return error_response

    # リクエストデータのスキーマバリデーション
    # Validate request payload against Pydantic schema
    payload, validation_error = validate_payload_model(
        data,
        EmailChangeRequest,
        error_message='メールアドレスの形式が正しくありません',
        status='fail',
    )
    if validation_error is not None:
        return validation_error

    new_email = payload.new_email
    # ユーザーが実在するか確認
    # Check if the user exists
    user = await run_blocking(get_user_by_id, user_id)
    if not user:
        return jsonify({'error': 'ユーザーが存在しません'}, status_code=404)

    # 現在のメールアドレスと同じ場合はエラー
    # Error if the new email matches the current email
    current_email = (user.get('email') or '').lower()
    if new_email == current_email:
        return jsonify(
            {'error': '現在のメールアドレスと同じです'},
            status_code=400,
        )

    # 既に他のユーザーがそのメールアドレスを登録していないか確認
    # Ensure the new email is not claimed by another active user
    existing = await run_blocking(get_user_by_email, new_email)
    if existing and existing.get('id') != user_id:
        # 不要なユーザー存在の漏洩を防ぐため、メッセージは汎用的なものに留める
        # Keep the error message generic to avoid leaking email existence.
        return jsonify(
            {'error': 'このメールアドレスは利用できません'},
            status_code=400,
        )

    # 6桁の認証コードを生成
    # Generate verification code
    code = generate_verification_code()
    
    # セッションに進捗状態・コード・タイムスタンプ等を記録
    # Record change progress state, code, and timestamps in session
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
        # メール送信を実行
        # Send confirmation email
        send_error = await _send_email_change_code(
            request=request,
            to_email=current_email,
            subject=subject,
            body_text=body_text,
            auth_limit_service=auth_limit_service,
            llm_daily_limit_service=llm_daily_limit_service,
        )
        if send_error:
            # 送信エラー時はセッションデータを消去
            # Wipe session state if sending fails
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


# メールアドレス変更コードを確認し、次の検証段階へ移行するか変更を完了するAPIエンドポイント
# API endpoint to verify email-change code, advancing stage or completing the update.
@chat_bp.post('/api/user/email/confirm_change', name='chat.confirm_email_change')
async def confirm_email_change(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
    llm_daily_limit_service: LlmDailyLimitService | None = Depends(get_llm_daily_limit_service),
):
    """
    入力された確認コードを検証し、現在のメールアドレス確認段階なら次の変更先アドレス確認へ、
    変更先アドレス確認段階ならメールアドレスの更新を実行します。
    Verifies the submitted confirmation code. Advances the stage or completes the email update process.
    """
    # ユーザーの認証チェック
    # Validate session authentication
    if 'user_id' not in request.session:
        return jsonify({'error': 'ログインが必要です'}, status_code=401)
    user_id = request.session['user_id']

    # JSONリクエストボディのチェック
    # Verify request body is JSON
    data, error_response = await require_json_dict(request, status='fail')
    if error_response is not None:
        return error_response

    # スキーマバリデーション
    # Validate request payload
    payload, validation_error = validate_payload_model(
        data,
        EmailChangeConfirmRequest,
        error_message='確認コードを入力してください',
        status='fail',
    )
    if validation_error is not None:
        return validation_error

    # セッション内の変更ステート取得
    # Retrieve current email change state from session
    state = request.session.get(EMAIL_CHANGE_SESSION_KEY)
    if not isinstance(state, dict) or not state.get('code') or not state.get('new_email'):
        return jsonify(
            {'status': 'fail', 'error': 'メールアドレス変更のセッション情報がありません。最初からやり直してください'},
            status_code=400,
        )

    issued_at = int(state.get('issued_at') or 0)
    attempts = int(state.get('attempts') or 0)

    # 確認コードの有効期限（TTL）を検証
    # Check if the code has expired
    if issued_at <= 0 or int(time.time()) - issued_at > EMAIL_CHANGE_CODE_TTL_SECONDS:
        _clear_email_change_session(request.session)
        return jsonify(
            {'status': 'fail', 'error': '確認コードの有効期限が切れています'},
            status_code=400,
        )

    # 最大試行回数の検証
    # Check if maximum attempts have been reached
    if attempts >= EMAIL_CHANGE_CODE_MAX_ATTEMPTS:
        _clear_email_change_session(request.session)
        return jsonify(
            {'status': 'fail', 'error': '確認コードの試行回数が上限に達しました'},
            status_code=429,
        )

    # 定数時間比較で入力コードを検証（タイミング攻撃防止）
    # Compare codes using constant-time comparison to prevent timing attacks
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
    
    # 段階1: 現在のメールアドレス確認完了。段階2（変更先アドレス確認）へ移行しメールを送信
    # Stage 1: Current email verified. Transition to Stage 2 (verify new email) and send email.
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
            # 変更先アドレス宛にコード送信
            # Send verification code to the new email address
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

    # ステート不正判定
    # Handle unexpected stage value
    if stage != EMAIL_CHANGE_STAGE_NEW:
        _clear_email_change_session(request.session)
        return jsonify(
            {'status': 'fail', 'error': 'メールアドレス変更の状態が不正です。最初からやり直してください'},
            status_code=400,
        )

    # 段階2: 変更先アドレスの確認完了。DB更新（コミット）を行う
    # Stage 2: New email verified. Commit the database changes.
    try:
        committed = await run_blocking(_commit_email_change, user_id, new_email)
    except Exception:
        _clear_email_change_session(request.session)
        return log_and_internal_server_error(
            logger,
            'Failed to commit email-change update.',
            status='fail',
        )

    # セッション内の変更データをクリア
    # Clean up the change state from the session
    _clear_email_change_session(request.session)
    if not committed:
        return jsonify(
            {'status': 'fail', 'error': 'このメールアドレスは利用できません'},
            status_code=409,
        )

    # セッションのユーザーメールアドレス情報を更新
    # Update active user email details in the session
    request.session['user_email'] = new_email
    return jsonify({'status': 'success', 'email': new_email})
