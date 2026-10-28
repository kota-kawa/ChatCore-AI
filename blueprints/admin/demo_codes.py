"""Admin API for issuing, listing and revoking demo access codes."""

from __future__ import annotations

import logging

from fastapi import Request

from services.datetime_serialization import serialize_datetime_iso
from services.demo_access import DemoCodeSummary, issue_demo_code, list_demo_codes, revoke_demo_code
from services.request_models import DemoAccessCodeCreateRequest
from services.usage_limits import load_usage_limit_settings, nano_usd_to_usd
from services.web import jsonify, log_and_internal_server_error, require_json_dict, validate_payload_model

from . import admin_bp
from .views import _admin_guard

logger = logging.getLogger(__name__)


def _serialize(summary: DemoCodeSummary, limit_usd: float) -> dict[str, object]:
    return {
        "id": summary.id,
        "label": summary.label,
        "status": summary.status,
        "created_at": serialize_datetime_iso(summary.created_at),
        "first_used_at": serialize_datetime_iso(summary.first_used_at),
        "expires_at": serialize_datetime_iso(summary.expires_at),
        "used_usd": None if summary.used_nano_usd is None else nano_usd_to_usd(summary.used_nano_usd),
        "limit_usd": limit_usd,
    }


def _limit_usd() -> float:
    return nano_usd_to_usd(load_usage_limit_settings().demo_total)


@admin_bp.get("/api/demo-codes", name="admin.api_list_demo_codes")
async def api_list_demo_codes(request: Request):
    guard = _admin_guard(request)
    if guard is not None:
        return guard
    try:
        summaries = await list_demo_codes()
    except Exception:
        return log_and_internal_server_error(logger, "Failed to list demo access codes.", status="fail")
    limit_usd = _limit_usd()
    return jsonify({"codes": [_serialize(summary, limit_usd) for summary in summaries]})


@admin_bp.post("/api/demo-codes", name="admin.api_issue_demo_code")
async def api_issue_demo_code(request: Request):
    guard = _admin_guard(request)
    if guard is not None:
        return guard
    data, error_response = await require_json_dict(request, status="fail")
    if data is None:
        return error_response
    payload, error_response = validate_payload_model(
        data,
        DemoAccessCodeCreateRequest,
        error_message="配布先の名前を1〜120文字で入力してください。",
        status="fail",
    )
    if payload is None:
        return error_response
    try:
        issued = await issue_demo_code(payload.label)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to issue a demo access code.", status="fail")
    return jsonify({"code": issued.code, "item": _serialize(issued.summary, _limit_usd())}, status_code=201)


@admin_bp.post("/api/demo-codes/{code_id}/revoke", name="admin.api_revoke_demo_code")
async def api_revoke_demo_code(request: Request, code_id: int):
    guard = _admin_guard(request)
    if guard is not None:
        return guard
    try:
        summary = await revoke_demo_code(code_id)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to revoke a demo access code.", status="fail")
    if summary is None:
        return jsonify({"status": "fail", "error": "コードが見つかりません。"}, status_code=404)
    return jsonify({"item": _serialize(summary, _limit_usd())})
