from __future__ import annotations

import logging

from fastapi import Request

from services.datetime_serialization import serialize_datetime_iso
from services.i18n import get_request_locale, translate
from services.usage_limits import UsageWindow, get_usage_status
from services.usage_subject import user_usage_subject
from services.web import jsonify

from . import chat_bp

logger = logging.getLogger(__name__)


# 金額は返さず、上限に対する割合だけを返す。単価や上限額を利用者に見せない合意のため。
# Only the share of each limit is returned, never amounts: the agreed design shows usage as a
# percentage rather than exposing prices or limit amounts.
def _serialize_window(window: UsageWindow | None) -> dict[str, object] | None:
    if window is None or window.limit_nano_usd <= 0:
        return None
    return {
        "used_ratio": min(window.used_nano_usd / window.limit_nano_usd, 1.0),
        "resets_at": serialize_datetime_iso(window.resets_at),
    }


@chat_bp.get("/api/user/usage-limits", name="chat.get_usage_limits")
async def get_usage_limits(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return jsonify(
            {"error": translate("common.login_required", locale=get_request_locale(request))},
            status_code=401,
        )
    try:
        status = await get_usage_status(user_usage_subject(user_id))
    except Exception:
        logger.exception("Failed to load usage limits.")
        return jsonify(
            {"error": translate("usage_limit.load_failed", locale=get_request_locale(request))},
            status_code=500,
        )
    return jsonify(
        {
            "daily": _serialize_window(status.daily),
            "weekly": _serialize_window(status.weekly),
            "monthly_budget_exhausted": status.monthly_budget_exhausted,
            "monthly_resets_at": serialize_datetime_iso(status.monthly_resets_at),
        }
    )
