import logging
import time

from fastapi import APIRouter, Depends, Request

from services.async_utils import run_blocking
from services.api_errors import DEFAULT_RETRY_AFTER_SECONDS, parse_retry_after_seconds
from services.auth_limits import (
    AuthLimitService,
    consume_auth_email_send_limits,
    consume_verification_attempt_limit,
    get_auth_limit_service,
)
from services.auth_session import establish_authenticated_session
from services.csrf import require_csrf
from services.email_service import send_email
from services.llm_daily_limit import (
    LlmDailyLimitService,
    consume_auth_email_daily_quota,
    get_seconds_until_daily_reset,
    get_llm_daily_limit_service,
)
from services.request_models import AuthCodeRequest, EmailRequest
from services.security import constant_time_compare, generate_verification_code
from services.users import (
    create_user,
    get_user_by_email,
    set_user_verified,
    get_user_by_id,
    copy_default_tasks_for_user,
)
from services.web import (
    jsonify,
    jsonify_rate_limited,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

# CSRF保護を依存関係として設定した FastAPI ルーターの初期化
# Initialize FastAPI router with CSRF protection enabled as dependencies.
verification_bp = APIRouter(dependencies=[Depends(require_csrf)])
logger = logging.getLogger(__name__)

# 認証コードの有効期限（秒）
# Time-To-Live (TTL) in seconds for the verification code.
VERIFICATION_CODE_TTL_SECONDS = 300

# 認証コード入力の最大試行回数
# Maximum number of attempts allowed for entering the verification code.
VERIFICATION_CODE_MAX_ATTEMPTS = 5

# 認証失敗時の HTTP ステータスコード (401 Unauthorized)
# HTTP status code for authentication failure (401 Unauthorized).
AUTH_FAILURE_STATUS_CODE = 401


# セッションから登録・認証用の一時データを削除する
# Clear temporary registration and verification data from the session.
def _clear_registration_verification_session(session: dict) -> None:
    """
    セッションから登録・認証用の一時データをクリアします。
    Clear temporary registration and verification data from the session.
    """
    # 認証コード、仮ユーザーID、仮メールアドレス、発行日時、試行回数をセッションから削除
    # Remove verification code, temporary user ID, temporary email, issued time, and attempt counts from the session.
    session.pop("verification_code", None)
    session.pop("temp_user_id", None)
    session.pop("temp_email", None)
    session.pop("verification_code_issued_at", None)
    session.pop("verification_code_attempts", None)


# 渡されたAuthLimitServiceを使用するか、リクエストから新しく解決するヘルパー関数
# Helper function to resolve the AuthLimitService from the request if not already provided.
def _resolve_auth_limit_service(
    request: Request,
    service: AuthLimitService | None,
) -> AuthLimitService:
    """
    引数のサービスインスタンスが有効ならそれを返し、無効ならリクエストから解決します。
    Return the provided AuthLimitService instance if it is valid; otherwise, resolve it from the request.
    """
    # サービスが渡されていればそれを返し、無ければリクエストから取得する
    # If the service instance is provided, return it; otherwise, resolve it from the request.
    if isinstance(service, AuthLimitService):
        return service
    return get_auth_limit_service(request)


# 渡されたLlmDailyLimitServiceを使用するか、リクエストから新しく解決するヘルパー関数
# Helper function to resolve the LlmDailyLimitService from the request if not already provided.
def _resolve_llm_daily_limit_service(
    request: Request,
    service: LlmDailyLimitService | None,
) -> LlmDailyLimitService:
    """
    引数のサービスインスタンスが有効ならそれを返し、無効ならリクエストから解決します。
    Return the provided LlmDailyLimitService instance if it is valid; otherwise, resolve it from the request.
    """
    # サービスが渡されていればそれを返し、無ければリクエストから取得する
    # If the service instance is provided, return it; otherwise, resolve it from the request.
    if isinstance(service, LlmDailyLimitService):
        return service
    return get_llm_daily_limit_service(request)


# ユーザー登録用の認証コードを生成し、メールで送信するエンドポイント
# Endpoint to generate a registration verification code and send it via email.
@verification_bp.post("/api/send_verification_email", name="verification.api_send_verification_email")
async def api_send_verification_email(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
    llm_daily_limit_service: LlmDailyLimitService | None = Depends(get_llm_daily_limit_service),
):
    """
    登録確認メールを生成して送信するAPIエンドポイント。
    API endpoint to generate and send a registration verification email.

    register.html から「確認メール送信」ボタン押下で呼ばれる
    - メールアドレスをDBに登録 (is_verified=False)
    - 6桁のコードを生成し、メールプロバイダ経由で送信
    - コードは session["verification_code"] に一時的に保存 (本番ではDBでもOK)
    - session["temp_user_id"] に仮保存

    Called when the "Send verification email" button is clicked on register.html.
    - Create/ensure a user exists with is_verified=False
    - Generate a 6-digit verification code and send it via email provider
    - Temporarily store the code and temporary user ID in session
    """
    # リクエストボディをJSONとして取得。不正な場合はエラーレスポンスを返却
    # Retrieve the request body as JSON. Return an error response if invalid.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # JSONデータを検証し、EmailRequestモデルにマッピング
    # Validate JSON data and map to EmailRequest model.
    payload, validation_error = validate_payload_model(
        data,
        EmailRequest,
        error_message="メールアドレスが指定されていません",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    # 各種制限確認サービスを解決
    # Resolve rate limit and daily quota limit services.
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    resolved_llm_daily_limit_service = _resolve_llm_daily_limit_service(
        request,
        llm_daily_limit_service,
    )

    email = payload.email
    # メール送信制限（短時間での連続送信防止）を確認・消費
    # Check and consume the rate limit for sending authentication emails.
    allowed, limit_error = consume_auth_email_send_limits(
        request,
        email,
        service=resolved_auth_limit_service,
    )
    if not allowed:
        return jsonify_rate_limited(
            limit_error or "試行回数が多すぎます。時間をおいて再試行してください。",
            retry_after=parse_retry_after_seconds(
                limit_error,
                default=DEFAULT_RETRY_AFTER_SECONDS,
            ),
            status="fail",
        )

    # 1日のメール送信制限（クォータ）を確認・消費
    # Check and consume the daily email quota.
    can_send_email, _, daily_limit = await run_blocking(
        consume_auth_email_daily_quota,
        service=resolved_llm_daily_limit_service,
    )
    if not can_send_email:
        return jsonify_rate_limited(
            (
                f"本日の認証メール送信上限（全ユーザー合計 {daily_limit} 件）に達しました。"
                "日付が変わってから再度お試しください。"
            ),
            retry_after=get_seconds_until_daily_reset(),
            status="fail",
        )

    # すでにユーザーがあれば再利用、なければ作成
    # Reuse existing user or create a new unverified user.
    user = await run_blocking(get_user_by_email, email)
    if not user:
        user_id = await run_blocking(create_user, email)
    else:
        user_id = user["id"]

    # 6桁コード生成→セッションへ
    # Generate a six-digit code and keep it in session temporarily.
    code = generate_verification_code()
    request.session["verification_code"] = code
    request.session["temp_user_id"] = user_id  # どのユーザーか紐付け
    request.session["temp_email"] = email  # rate-limit key (cross-session)
    request.session["verification_code_issued_at"] = int(time.time())
    request.session["verification_code_attempts"] = 0

    # メールの件名と本文を定義
    # Define the subject and body text of the email.
    subject = "AIチャットサービス: 認証コード"
    body_text = f"以下の認証コードを登録画面に入力してください。\n\n認証コード: {code}"
    try:
        # メール送信を実行
        # Attempt to send the email with verification code.
        await run_blocking(send_email, to_address=email, subject=subject, body_text=body_text)
        # 成功レスポンスを返却
        # Return a success response.
        return jsonify({"status": "success"})
    except Exception:
        # 送信失敗時はログを記録して500エラーを返却
        # Log error and return 500 server error response on failure.
        return log_and_internal_server_error(
            logger,
            "Failed to send registration verification email.",
            status="fail",
        )


# ユーザーから送信された認証コードを検証し、成功すればユーザーを有効化してログインさせるエンドポイント
# Endpoint to verify the submitted registration code, activate the user, and establish a session.
@verification_bp.post("/api/verify_registration_code", name="verification.api_verify_registration_code")
async def api_verify_registration_code(
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
):
    """
    ユーザーが入力した登録用認証コードを検証するAPIエンドポイント。
    API endpoint to verify the registration verification code submitted by the user.

    register.html の「認証する」ボタンで呼ばれる。
    ・セッション保存の認証コードと照合
    ・一致すればユーザーを is_verified=True にしログイン状態へ
    ・このタイミングで初期タスクをユーザー専用に複製

    Called by the "Verify" action on register page.
    - Compare submitted code with session code
    - Mark user as verified and log them in
    - Copy default tasks for the verified user
    """
    # リクエストボディをJSONとして取得。不正な場合はエラーレスポンスを返却
    # Retrieve the request body as JSON. Return an error response if invalid.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # JSONデータを検証し、AuthCodeRequestモデルにマッピング
    # Validate JSON data and map to EmailRequest model.
    payload, validation_error = validate_payload_model(
        data,
        AuthCodeRequest,
        error_message="認証コードが違います。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    # リクエストされたコード、セッション情報、仮ユーザーIDを取得
    # Retrieve the submitted code, session information, and temporary user ID.
    user_code = payload.authCode
    session = request.session
    session_code = session.get("verification_code")
    user_id = session.get("temp_user_id")

    # セッション内に認証情報が存在するか確認
    # Verify that session verification information exists.
    if not session_code or not user_id:
        return jsonify(
            {"status": "fail", "error": "セッション情報がありません。最初からやり直してください"},
            status_code=AUTH_FAILURE_STATUS_CODE,
        )

    # 認証コードの発行時刻と試行回数を取得
    # Retrieve code issuance timestamp and verification attempt count.
    issued_at = int(session.get("verification_code_issued_at") or 0)
    attempts = int(session.get("verification_code_attempts") or 0)

    # 認証コードの有効期限（TTL）を確認
    # Verify the code expiration (TTL).
    if issued_at <= 0 or int(time.time()) - issued_at > VERIFICATION_CODE_TTL_SECONDS:
        _clear_registration_verification_session(session)
        return jsonify(
            {"status": "fail", "error": "認証コードの有効期限が切れています。"},
            status_code=AUTH_FAILURE_STATUS_CODE,
        )

    # 試行回数がセッション上限を超えているか確認
    # Check if the attempt count has reached the maximum limit in the current session.
    if attempts >= VERIFICATION_CODE_MAX_ATTEMPTS:
        _clear_registration_verification_session(session)
        return jsonify(
            {"status": "fail", "error": "認証コードの試行回数が上限に達しました。"},
            status_code=AUTH_FAILURE_STATUS_CODE,
        )

    # メールアドレス・IP単位での認証コード試行制限を適用
    # Apply verification attempt rate limits per email/IP (cross-session).
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    email_for_limit = str(session.get("temp_email") or "")
    allowed, limit_error = await run_blocking(
        consume_verification_attempt_limit,
        request,
        email_for_limit,
        service=resolved_auth_limit_service,
    )
    if not allowed:
        return jsonify_rate_limited(
            limit_error or "認証コードの試行回数が多すぎます。時間をおいて再試行してください。",
            retry_after=parse_retry_after_seconds(
                limit_error,
                default=DEFAULT_RETRY_AFTER_SECONDS,
            ),
            status="fail",
        )

    # ユーザーが入力したコードとセッションのコードを定数時間比較で安全に照合
    # Perform a constant-time comparison to securely match the user-provided code with the session code.
    submitted_code = str(user_code or "")
    if not constant_time_compare(submitted_code, str(session_code)):
        # 不一致の場合は試行回数をインクリメント
        # Increment the attempt count if the code does not match.
        attempts += 1
        session["verification_code_attempts"] = attempts
        # 試行回数が上限に達した場合はセッションをクリアしてエラーを返す
        # If attempt count reaches the maximum limit, clear the session and return an error.
        if attempts >= VERIFICATION_CODE_MAX_ATTEMPTS:
            _clear_registration_verification_session(session)
            return jsonify(
                {"status": "fail", "error": "認証コードの試行回数が上限に達しました。"},
                status_code=AUTH_FAILURE_STATUS_CODE,
            )
        return jsonify(
            {"status": "fail", "error": "認証コードが一致しません。"},
            status_code=AUTH_FAILURE_STATUS_CODE,
        )

    # ここから成功処理 ----------------------------------------------------
    # Success path starts here.
    user = await run_blocking(get_user_by_id, user_id)
    if not user:
        # ユーザーが見つからない場合はセッション情報の一部をクリアしてエラーを返す
        # If the user is not found, clear some session data and return an error.
        _clear_registration_verification_session(session)
        session.pop("user_id", None)
        session.pop("user_email", None)
        return jsonify(
            {"status": "fail", "error": "ユーザーが存在しません"},
            status_code=AUTH_FAILURE_STATUS_CODE,
        )

    # ユーザーを認証済みに更新
    # Set the user status to verified.
    await run_blocking(set_user_verified, user_id)                 # ユーザーを認証済みに
    
    # 共通の初期タスクを新規ユーザー用に複製
    # Copy shared default tasks to this newly verified user.
    await run_blocking(copy_default_tasks_for_user, user_id)       # ★ 共通タスクを複製 ★

    # 認証済みセッションの確立（ログイン状態に移行）
    # Establish an authenticated session (transitioning to logged-in state).
    establish_authenticated_session(request, int(user_id), user["email"])

    # 登録・認証用の一時セッション情報をクリーンアップ
    # Clear temporary registration/verification session data.
    _clear_registration_verification_session(session)

    # パスキー設定をオファーするフラグを付けて成功レスポンスを返却
    # Return a success response, offering WebAuthn/passkey setup.
    return jsonify(
        {
            "status": "success",
            "flow": "register",
            "offer_passkey_setup": True,
        }
    )
