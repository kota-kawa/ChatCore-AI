from __future__ import annotations

from typing import Any

from fastapi import Depends, Request

from blueprints.auth_common import (
    _clear_login_verification_session,
    _copy_default_tasks_after_login,
    _resolve_auth_limit_service,
    _resolve_llm_daily_limit_service,
)
from blueprints.auth_support import (
    dep,
    get_auth_limit_service_dependency,
    get_llm_daily_limit_service_dependency,
)


async def api_send_email_code(
    request: Request,
    auth_limit_service: Any | None = Depends(get_auth_limit_service_dependency),
    llm_daily_limit_service: Any | None = Depends(get_llm_daily_limit_service_dependency),
):
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    resolved_llm_daily_limit_service = _resolve_llm_daily_limit_service(
        request,
        llm_daily_limit_service,
    )

    data, error_response = await dep("require_json_dict")(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = dep("validate_payload_model")(
        data,
        dep("EmailRequest"),
        error_message="メールアドレスが指定されていません",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    user = await dep("run_blocking")(dep("get_user_by_email"), payload.email)
    if user and user.get("is_verified"):
        return await dep("api_send_login_code")(
            request,
            auth_limit_service=resolved_auth_limit_service,
            llm_daily_limit_service=resolved_llm_daily_limit_service,
        )
    return await dep("api_send_verification_email")(
        request,
        auth_limit_service=resolved_auth_limit_service,
        llm_daily_limit_service=resolved_llm_daily_limit_service,
    )


async def api_verify_email_code(request: Request):
    session = request.session
    if session.get("login_verification_code") and session.get("login_temp_user_id"):
        return await dep("api_verify_login_code")(request)
    if session.get("verification_code") and session.get("temp_user_id"):
        return await dep("api_verify_registration_code")(request)

    return dep("jsonify")(
        {"status": "fail", "error": "セッション情報がありません。最初からやり直してください"},
        status_code=dep("AUTH_FAILURE_STATUS_CODE"),
    )


async def api_send_login_code(
    request: Request,
    auth_limit_service: Any | None = Depends(get_auth_limit_service_dependency),
    llm_daily_limit_service: Any | None = Depends(get_llm_daily_limit_service_dependency),
):
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    resolved_llm_daily_limit_service = _resolve_llm_daily_limit_service(
        request,
        llm_daily_limit_service,
    )

    data, error_response = await dep("require_json_dict")(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = dep("validate_payload_model")(
        data,
        dep("EmailRequest"),
        error_message="メールアドレスが指定されていません",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    email = payload.email
    allowed, limit_error = dep("consume_auth_email_send_limits")(
        request,
        email,
        service=resolved_auth_limit_service,
    )
    if not allowed:
        return dep("jsonify_rate_limited")(
            limit_error or "試行回数が多すぎます。時間をおいて再試行してください。",
            retry_after=dep("parse_retry_after_seconds")(
                limit_error,
                default=dep("DEFAULT_RETRY_AFTER_SECONDS"),
            ),
            status="fail",
        )

    user = await dep("run_blocking")(dep("get_user_by_email"), email)
    if not user or not user["is_verified"]:
        return dep("jsonify")(
            {"status": "fail", "error": "ユーザーが存在しないか、認証されていません"},
            status_code=dep("AUTH_FAILURE_STATUS_CODE"),
        )

    can_send_email, _, daily_limit = await dep("run_blocking")(
        dep("consume_auth_email_daily_quota"),
        service=resolved_llm_daily_limit_service,
    )
    if not can_send_email:
        return dep("jsonify_rate_limited")(
            (
                f"本日の認証メール送信上限（全ユーザー合計 {daily_limit} 件）に達しました。"
                "日付が変わってから再度お試しください。"
            ),
            retry_after=dep("get_seconds_until_daily_reset")(),
            status="fail",
        )

    code = dep("generate_verification_code")()
    request.session["login_verification_code"] = code
    request.session["login_temp_user_id"] = user["id"]
    request.session["login_temp_email"] = email
    request.session["login_verification_code_issued_at"] = int(dep("time").time())
    request.session["login_verification_code_attempts"] = 0

    subject = "AIチャットサービス: ログイン認証コード"
    body_text = f"以下の認証コードをログイン画面に入力してください。\n\n認証コード: {code}"
    try:
        await dep("run_blocking")(
            dep("send_email"),
            to_address=email,
            subject=subject,
            body_text=body_text,
        )
        return dep("jsonify")({"status": "success", "message": "認証コードを送信しました"})
    except Exception:
        return dep("log_and_internal_server_error")(
            dep("logger"),
            "Failed to send login verification code email.",
            status="fail",
        )


async def api_verify_login_code(
    request: Request,
    auth_limit_service: Any | None = Depends(get_auth_limit_service_dependency),
):
    data, error_response = await dep("require_json_dict")(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = dep("validate_payload_model")(
        data,
        dep("AuthCodeRequest"),
        error_message="認証コードが違います",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    auth_code = payload.authCode
    session = request.session
    session_code = session.get("login_verification_code")
    user_id = session.get("login_temp_user_id")
    if not session_code or not user_id:
        return dep("jsonify")(
            {"status": "fail", "error": "セッション情報がありません。最初からやり直してください"},
            status_code=dep("AUTH_FAILURE_STATUS_CODE"),
        )

    issued_at = int(session.get("login_verification_code_issued_at") or 0)
    attempts = int(session.get("login_verification_code_attempts") or 0)
    if issued_at <= 0 or int(dep("time").time()) - issued_at > dep("LOGIN_VERIFICATION_CODE_TTL_SECONDS"):
        _clear_login_verification_session(session)
        return dep("jsonify")(
            {"status": "fail", "error": "認証コードの有効期限が切れています。"},
            status_code=dep("AUTH_FAILURE_STATUS_CODE"),
        )

    if attempts >= dep("LOGIN_VERIFICATION_CODE_MAX_ATTEMPTS"):
        _clear_login_verification_session(session)
        return dep("jsonify")(
            {"status": "fail", "error": "認証コードの試行回数が上限に達しました。"},
            status_code=dep("AUTH_FAILURE_STATUS_CODE"),
        )

    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    email_for_limit = str(session.get("login_temp_email") or "")
    allowed, limit_error = await dep("run_blocking")(
        dep("consume_verification_attempt_limit"),
        request,
        email_for_limit,
        service=resolved_auth_limit_service,
    )
    if not allowed:
        return dep("jsonify_rate_limited")(
            limit_error or "認証コードの試行回数が多すぎます。時間をおいて再試行してください。",
            retry_after=dep("parse_retry_after_seconds")(
                limit_error,
                default=dep("DEFAULT_RETRY_AFTER_SECONDS"),
            ),
            status="fail",
        )

    submitted_code = str(auth_code or "")
    if dep("constant_time_compare")(submitted_code, str(session_code)):
        user = await dep("run_blocking")(dep("get_user_by_id"), user_id)
        if not user or not user.get("is_verified"):
            _clear_login_verification_session(session)
            session.pop("user_id", None)
            session.pop("user_email", None)
            return dep("jsonify")(
                {"status": "fail", "error": "ユーザーが存在しないか、認証されていません"},
                status_code=dep("AUTH_FAILURE_STATUS_CODE"),
            )

        dep("establish_authenticated_session")(request, int(user_id), user["email"] if user else "")
        _clear_login_verification_session(session)
        await _copy_default_tasks_after_login(
            int(user_id),
            context="Email login verification",
        )
        return dep("jsonify")(
            {
                "status": "success",
                "message": "ログインに成功しました",
                "flow": "login",
                "offer_passkey_setup": False,
            }
        )

    attempts += 1
    session["login_verification_code_attempts"] = attempts
    if attempts >= dep("LOGIN_VERIFICATION_CODE_MAX_ATTEMPTS"):
        _clear_login_verification_session(session)
        return dep("jsonify")(
            {"status": "fail", "error": "認証コードの試行回数が上限に達しました。"},
            status_code=dep("AUTH_FAILURE_STATUS_CODE"),
        )
    return dep("jsonify")(
        {"status": "fail", "error": "認証コードが一致しません。"},
        status_code=dep("AUTH_FAILURE_STATUS_CODE"),
    )
