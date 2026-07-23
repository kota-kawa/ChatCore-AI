from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from blueprints.memo.helpers import user_id_from_session
from services.api_errors import ApiServiceError
from services.async_utils import run_blocking
from services.context_vault_candidate_service import (
    DEFAULT_CONTEXT_CANDIDATE_LIST_LIMIT,
    MAX_CONTEXT_CANDIDATE_LIST_LIMIT,
    approve_candidate,
    get_extraction_settings,
    list_candidates,
    reject_candidate,
    update_extraction_settings,
)
from services.context_vault_service import (
    MAX_CONTEXT_LIST_LIMIT,
    create_fact,
    list_facts,
    update_fact,
)
from services.context_vault_portability import (
    build_export,
    confirm_import,
    preview_import,
)
from services.csrf import require_csrf
from services.error_messages import (
    ERROR_CONTEXT_EXTRACTION_SETTINGS_PAYLOAD_INVALID,
    ERROR_CONTEXT_FACT_CANDIDATE_APPROVE_PAYLOAD_INVALID,
    ERROR_CONTEXT_FACT_CANDIDATE_REJECT_PAYLOAD_INVALID,
    ERROR_CONTEXT_FACT_CANDIDATE_STATUS_INVALID,
    ERROR_CONTEXT_VAULT_EXPORT_FORMAT_INVALID,
    ERROR_CONTEXT_VAULT_IMPORT_PAYLOAD_INVALID,
    ERROR_CONTEXT_VAULT_IMPORT_REQUEST_TOO_LARGE,
    ERROR_CONTEXT_VAULT_PORTABILITY_FAILED,
    ERROR_LOGIN_REQUIRED,
)
from services.request_models import (
    ContextExtractionSettingsUpdateRequest,
    ContextFactCandidateApproveRequest,
    ContextFactCandidateRejectRequest,
    ContextFactCreateRequest,
    ContextFactUpdateRequest,
    ContextVaultImportConfirmRequest,
    ContextVaultImportPreviewRequest,
)
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
_VALID_CANDIDATE_STATUSES = {"pending", "approved", "rejected"}
_VALID_PORTABILITY_FORMATS = {"json", "markdown"}
_MAX_CONTEXT_VAULT_IMPORT_REQUEST_BYTES = 32 * 1024 * 1024


async def _require_bounded_import_json(request: Request):
    """Read an import wrapper with a hard cap for fixed and chunked bodies."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_CONTEXT_VAULT_IMPORT_REQUEST_BYTES:
                return None, jsonify(
                    {
                        "status": "fail",
                        "error": ERROR_CONTEXT_VAULT_IMPORT_REQUEST_TOO_LARGE,
                    },
                    status_code=413,
                )
        except ValueError:
            pass

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_CONTEXT_VAULT_IMPORT_REQUEST_BYTES:
            return None, jsonify(
                {
                    "status": "fail",
                    "error": ERROR_CONTEXT_VAULT_IMPORT_REQUEST_TOO_LARGE,
                },
                status_code=413,
            )
        body.extend(chunk)
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError):
        return None, jsonify(
            {"status": "fail", "error": ERROR_CONTEXT_VAULT_IMPORT_PAYLOAD_INVALID},
            status_code=400,
        )
    if not isinstance(data, dict):
        return None, jsonify(
            {"status": "fail", "error": ERROR_CONTEXT_VAULT_IMPORT_PAYLOAD_INVALID},
            status_code=400,
        )
    return data, None


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


@context_vault_bp.get("/export", name="context_vault.api_export")
async def api_export_context_vault(request: Request, format: str = "json"):
    """Download every owner fact in a safe versioned JSON or Markdown document."""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    if format not in _VALID_PORTABILITY_FORMATS:
        return jsonify(
            {"status": "fail", "error": ERROR_CONTEXT_VAULT_EXPORT_FORMAT_INVALID},
            status_code=400,
        )
    try:
        content, media_type, filename = await run_blocking(build_export, user_id, format)
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(
            logger,
            ERROR_CONTEXT_VAULT_PORTABILITY_FAILED,
            status="fail",
        )


@context_vault_bp.post("/import/preview", name="context_vault.api_import_preview")
async def api_preview_context_vault_import(request: Request):
    """Validate a portability document and issue a short-lived confirmation token."""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    data, error_response = await _require_bounded_import_json(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        ContextVaultImportPreviewRequest,
        error_message=ERROR_CONTEXT_VAULT_IMPORT_PAYLOAD_INVALID,
        status="fail",
    )
    if validation_error is not None:
        return validation_error
    try:
        result = await run_blocking(
            preview_import,
            user_id,
            payload.format,
            payload.content,
        )
        return jsonify(result.model_dump())
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(
            logger,
            ERROR_CONTEXT_VAULT_PORTABILITY_FAILED,
            status="fail",
        )


@context_vault_bp.post("/import", name="context_vault.api_import")
async def api_import_context_vault(request: Request):
    """Append only the exact document accepted by a preceding dry-run."""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    data, error_response = await _require_bounded_import_json(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        ContextVaultImportConfirmRequest,
        error_message=ERROR_CONTEXT_VAULT_IMPORT_PAYLOAD_INVALID,
        status="fail",
    )
    if validation_error is not None:
        return validation_error
    try:
        result = await run_blocking(
            confirm_import,
            user_id,
            payload.format,
            payload.content,
            payload.preview_token,
        )
        return jsonify(result.model_dump())
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(
            logger,
            ERROR_CONTEXT_VAULT_PORTABILITY_FAILED,
            status="fail",
        )


@context_vault_bp.get("/candidates", name="context_vault.api_list_candidates")
async def api_list_context_fact_candidates(
    request: Request,
    status: str = "pending",
    limit: int = DEFAULT_CONTEXT_CANDIDATE_LIST_LIMIT,
    cursor: str | None = None,
):
    """ユーザー確認待ちの抽出候補をkeysetページングで取得する。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    if status not in _VALID_CANDIDATE_STATUSES:
        return jsonify(
            {"status": "fail", "error": ERROR_CONTEXT_FACT_CANDIDATE_STATUS_INVALID},
            status_code=400,
        )

    safe_limit = max(1, min(int(limit), MAX_CONTEXT_CANDIDATE_LIST_LIMIT))
    try:
        result = await run_blocking(
            list_candidates,
            user_id,
            status=status,
            limit=safe_limit,
            cursor=cursor,
        )
        return jsonify(result.model_dump())
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")


@context_vault_bp.put(
    "/candidates/{candidate_id:int}/approve",
    name="context_vault.api_approve_candidate",
)
async def api_approve_context_fact_candidate(request: Request, candidate_id: int):
    """候補を必要に応じて編集し、activeなコンテキスト事実へ昇格する。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        ContextFactCandidateApproveRequest,
        error_message=ERROR_CONTEXT_FACT_CANDIDATE_APPROVE_PAYLOAD_INVALID,
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        result = await run_blocking(
            approve_candidate,
            user_id,
            candidate_id,
            expected_revision=payload.revision,
            fact_type=payload.fact_type,
            title=payload.title,
            content=payload.content,
            importance=payload.importance,
        )
        return jsonify({"status": "success", **result.model_dump()})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(logger, CONTEXT_FACT_CREATE_ERROR, status="fail")


@context_vault_bp.put(
    "/candidates/{candidate_id:int}/reject",
    name="context_vault.api_reject_candidate",
)
async def api_reject_context_fact_candidate(request: Request, candidate_id: int):
    """候補をrevision競合安全に却下する。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        ContextFactCandidateRejectRequest,
        error_message=ERROR_CONTEXT_FACT_CANDIDATE_REJECT_PAYLOAD_INVALID,
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        candidate = await run_blocking(
            reject_candidate,
            user_id,
            candidate_id,
            expected_revision=payload.revision,
        )
        return jsonify({"status": "success", "candidate": candidate.model_dump()})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(logger, CONTEXT_FACT_UPDATE_ERROR, status="fail")


@context_vault_bp.get(
    "/extraction-settings",
    name="context_vault.api_get_extraction_settings",
)
async def api_get_context_extraction_settings(request: Request):
    """現在の会話コンテキスト自動抽出opt-in設定を取得する。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    try:
        result = await run_blocking(get_extraction_settings, user_id)
        return jsonify(result.model_dump())
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(logger, CONTEXT_FACT_UPDATE_ERROR, status="fail")


@context_vault_bp.put(
    "/extraction-settings",
    name="context_vault.api_update_extraction_settings",
)
async def api_update_context_extraction_settings(request: Request):
    """会話コンテキスト自動抽出をユーザーの明示操作で有効・無効化する。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        ContextExtractionSettingsUpdateRequest,
        error_message=ERROR_CONTEXT_EXTRACTION_SETTINGS_PAYLOAD_INVALID,
        status="fail",
    )
    if validation_error is not None:
        return validation_error
    try:
        result = await run_blocking(update_extraction_settings, user_id, payload.enabled)
        return jsonify({"status": "success", **result.model_dump()})
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
            importance=payload.importance,
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
            importance=payload.importance,
        )
        return jsonify({"status": "success", "fact": fact.model_dump()})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(logger, CONTEXT_FACT_UPDATE_ERROR, status="fail")
