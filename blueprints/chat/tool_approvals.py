"""Routes for chat approval cards: deciding a card, and listing or revoking "always approve".

判断と実行は services/chat_tool_approval_service.py が持ち、ここは認証・入力・レート制限・
応答の形だけを扱う。CSRF は chat_bp の依存で全ルートに掛かる。
The service (services/chat_tool_approval_service.py) owns deciding and running; these routes
only handle authentication, input, rate limits and the response shape. CSRF applies to every
route through the chat_bp dependency.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import Depends, Request

from services.api_errors import ApiServiceError
from services.async_utils import run_blocking
from services.auth_limits import AuthLimitService, consume_rate_limit, get_auth_limit_service
from services.chat_tool_approval_service import (
    ChatToolRateLimitedError,
    decide_tool_approval,
    list_auto_approvals,
    revoke_auto_approval,
)
from services.error_messages import (
    ERROR_LOGIN_REQUIRED,
    ERROR_TOOL_APPROVAL_DECISION_INVALID,
    ERROR_TOOL_APPROVAL_NOT_FOUND,
    ERROR_TOOL_APPROVAL_RATE_LIMITED_TEMPLATE,
)
from services.request_models import ToolApprovalDecisionRequest
from services.response_models import (
    ToolApprovalDecisionResponse,
    ToolAutoApprovalRevokeResponse,
    ToolAutoApprovalsResponse,
)
from services.web import (
    jsonify,
    jsonify_rate_limited,
    jsonify_service_error,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

from . import chat_bp

logger = logging.getLogger(__name__)

# 決定 API の連打を抑える。カード1枚は1回決めれば終わるので、人の操作としては十分に余裕がある。
# Throttle the decision API. One card is decided once, so this leaves ample room for a person.
TOOL_APPROVAL_DECIDE_RATE_KEY = "chat_tool_approval:decide:user"
TOOL_APPROVAL_DECIDE_LIMIT = 30
TOOL_APPROVAL_DECIDE_WINDOW_SECONDS = 60


def _authenticated_user_id(request: Request) -> int | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def _login_required():
    return jsonify({"error": ERROR_LOGIN_REQUIRED}, status_code=403)


def _parse_approval_id(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


@chat_bp.post("/api/chat/tool-approvals/{approval_id}/decision", name="chat.decide_tool_approval")
async def decide_chat_tool_approval(
    approval_id: str,
    request: Request,
    auth_limit_service: AuthLimitService | None = Depends(get_auth_limit_service),
):
    user_id = _authenticated_user_id(request)
    if user_id is None:
        return _login_required()
    parsed_id = _parse_approval_id(approval_id)
    if parsed_id is None:
        return jsonify({"error": ERROR_TOOL_APPROVAL_NOT_FOUND, "code": "approval_not_found"}, status_code=404)

    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        ToolApprovalDecisionRequest,
        error_message=ERROR_TOOL_APPROVAL_DECISION_INVALID,
    )
    if validation_error is not None:
        return validation_error

    allowed, _, retry_after = await run_blocking(
        consume_rate_limit,
        TOOL_APPROVAL_DECIDE_RATE_KEY,
        str(user_id),
        limit=TOOL_APPROVAL_DECIDE_LIMIT,
        window_seconds=TOOL_APPROVAL_DECIDE_WINDOW_SECONDS,
        service=auth_limit_service,
    )
    if not allowed:
        return jsonify_rate_limited(
            ERROR_TOOL_APPROVAL_RATE_LIMITED_TEMPLATE.format(seconds=retry_after),
            retry_after=retry_after,
        )

    try:
        card = await decide_tool_approval(
            user_id,
            parsed_id,
            payload.decision,
            auth_limit_service=auth_limit_service,
        )
    except ChatToolRateLimitedError as exc:
        return jsonify_rate_limited(exc.message, retry_after=exc.retry_after)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to decide a chat tool approval.")
    return jsonify(ToolApprovalDecisionResponse(approval=card).model_dump(exclude_none=True))


@chat_bp.get("/api/chat/tool-auto-approvals", name="chat.list_tool_auto_approvals")
async def get_chat_tool_auto_approvals(request: Request):
    user_id = _authenticated_user_id(request)
    if user_id is None:
        return _login_required()
    try:
        grants = await list_auto_approvals(user_id)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to list chat tool auto approvals.")
    return jsonify(ToolAutoApprovalsResponse(grants=grants).model_dump())


@chat_bp.delete("/api/chat/tool-auto-approvals/{tool_name}", name="chat.revoke_tool_auto_approval")
async def delete_chat_tool_auto_approval(tool_name: str, request: Request):
    user_id = _authenticated_user_id(request)
    if user_id is None:
        return _login_required()
    try:
        revoked = await revoke_auto_approval(user_id, tool_name)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to revoke a chat tool auto approval.")
    return jsonify(ToolAutoApprovalRevokeResponse(revoked=revoked).model_dump())
