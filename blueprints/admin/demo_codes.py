"""デモ用アクセスコードの発行・一覧・失効を行う管理者向け API。すべて管理者セッションを要求する。

Admin API for issuing, listing and revoking demo access codes; every route requires an admin session.
"""

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


# 管理画面へ返す形に整える。利用額は nano USD から USD に換算し、上限額（limit_usd）を添える。
# Shape a summary for the admin UI: convert usage from nano USD to USD and attach the limit.
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


# デモコード1つあたりの総額上限（USD）。設定値から毎回読む。
# Total spending limit per demo code in USD, read from the settings on each call.
def _limit_usd() -> float:
    return nano_usd_to_usd(load_usage_limit_settings().demo_total)


# 発行済みのデモコードを一覧で返す。
# List issued demo codes.
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


# 配布先の名前（label）を受け取ってデモコードを発行する。コードの平文が返るのはこの応答だけ。
# Issue a demo code for the given recipient label; the plain code is returned only in this response.
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


# 指定したデモコードを失効させる。存在しなければ 404。
# Revoke the given demo code; answers 404 when it does not exist.
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
