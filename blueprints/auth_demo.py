"""Sign in with a demo access code handed to one recipient."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from services.api_errors import DEFAULT_RETRY_AFTER_SECONDS, parse_retry_after_seconds
from services.async_utils import run_blocking
from services.auth_limits import consume_demo_login_limit
from services.auth_session import establish_authenticated_session
from services.csrf import require_csrf
from services.datetime_serialization import serialize_datetime_iso
from services.demo_access import redeem_demo_code
from services.i18n import get_request_locale, translate
from services.request_models import DemoLoginRequest
from services.web import (
    jsonify,
    jsonify_rate_limited,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

auth_demo_bp = APIRouter(dependencies=[Depends(require_csrf)])
logger = logging.getLogger(__name__)


@auth_demo_bp.post("/api/auth/demo-login", name="auth.api_demo_login")
async def api_demo_login(request: Request):
    locale = get_request_locale(request)
    data, error_response = await require_json_dict(request)
    if data is None:
        return error_response
    payload, error_response = validate_payload_model(
        data,
        DemoLoginRequest,
        error_message=translate("demo_access.invalid_code", locale),
    )
    if payload is None:
        return error_response

    allowed, limit_error = await run_blocking(consume_demo_login_limit, request)
    if not allowed:
        return jsonify_rate_limited(
            limit_error or translate("demo_access.invalid_code", locale),
            retry_after=parse_retry_after_seconds(limit_error, default=DEFAULT_RETRY_AFTER_SECONDS),
        )

    try:
        sign_in = await redeem_demo_code(payload.code)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to sign in with a demo access code.",
            message=translate("demo_access.sign_in_failed", locale),
        )
    # 存在しない・停止・期限切れを区別して返すと、コードが実在するかを探る手がかりになる。
    # Telling unknown, revoked and ended codes apart would let someone probe which codes exist.
    if sign_in is None:
        return jsonify({"error": translate("demo_access.invalid_code", locale)}, status_code=401)

    establish_authenticated_session(request, sign_in.user_id, sign_in.email)
    return jsonify({"status": "success", "expires_at": serialize_datetime_iso(sign_in.expires_at)})
