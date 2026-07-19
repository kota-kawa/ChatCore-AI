from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from blueprints.memo.helpers import user_id_from_session
from services.api_errors import ApiServiceError
from services.async_utils import run_blocking
from services.context_vault_service import (
    MAX_CONTEXT_LIST_LIMIT,
    create_fact,
    list_facts,
    update_fact,
)
from services.csrf import require_csrf
from services.error_messages import ERROR_LOGIN_REQUIRED
from services.request_models import ContextFactCreateRequest, ContextFactUpdateRequest
from services.web import (
    jsonify,
    jsonify_service_error,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

from .constants import (
    CONTEXT_FACT_CREATE_ERROR,
    CONTEXT_FACT_UPDATE_ERROR,
    DEFAULT_CONTEXT_LIST_LIMIT,
)

# CSRF保護を設定したパーソナル・コンテキスト金庫用APIRouter。
# APIRouter for the personal context vault, with CSRF protection.
context_vault_bp = APIRouter(prefix="/api/context-facts", dependencies=[Depends(require_csrf)])
logger = logging.getLogger("blueprints.context_vault")

_VALID_FACT_TYPES = {"preference", "profile", "project", "decision", "reference"}
_VALID_STATUSES = {"active", "deprecated"}


@context_vault_bp.get("", name="context_vault.api_list")
async def api_list_context_facts(
    request: Request,
    fact_type: str | None = None,
    status: str = "active",
    limit: int = DEFAULT_CONTEXT_LIST_LIMIT,
    cursor: str | None = None,
):
    """コンテキスト事実の一覧を取得する（種類・状態でフィルタ、keyset ページング）。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    if fact_type is not None and fact_type not in _VALID_FACT_TYPES:
        return jsonify({"status": "fail", "error": "種類の指定が不正です。"}, status_code=400)
    if status not in _VALID_STATUSES:
        return jsonify({"status": "fail", "error": "状態の指定が不正です。"}, status_code=400)

    safe_limit = max(1, min(int(limit), MAX_CONTEXT_LIST_LIMIT))
    try:
        result = await run_blocking(
            list_facts,
            user_id,
            fact_type=fact_type,
            status=status,
            limit=safe_limit,
            cursor=cursor,
        )
        return jsonify(result.model_dump())
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")


@context_vault_bp.post("", name="context_vault.api_create")
async def api_create_context_fact(request: Request):
    """コンテキスト事実を新規作成する。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        ContextFactCreateRequest,
        error_message="種類・タイトル・内容を入力してください。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        fact = await run_blocking(
            create_fact,
            user_id,
            fact_type=payload.fact_type,
            title=payload.title,
            content=payload.content,
        )
        return jsonify({"status": "success", "fact": fact.model_dump()})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(logger, CONTEXT_FACT_CREATE_ERROR, status="fail")


@context_vault_bp.put("/{fact_id:int}", name="context_vault.api_update")
async def api_update_context_fact(request: Request, fact_id: int):
    """コンテキスト事実を更新する（無効化・復元も status で行う、revision で競合検出）。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        ContextFactUpdateRequest,
        error_message="更新内容とrevisionを指定してください。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        fact = await run_blocking(
            update_fact,
            user_id,
            fact_id,
            expected_revision=payload.revision,
            title=payload.title,
            content=payload.content,
            fact_type=payload.fact_type,
            status=payload.status,
        )
        return jsonify({"status": "success", "fact": fact.model_dump()})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(logger, CONTEXT_FACT_UPDATE_ERROR, status="fail")
