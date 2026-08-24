from __future__ import annotations

import logging
from typing import Any

from fastapi import Request

from services.chat_service import get_user_preferred_locale, update_user_preferred_locale
from services.i18n import (
    PREFERRED_LOCALE_LOADED_SESSION_KEY,
    PREFERRED_LOCALE_SESSION_KEY,
    get_request_locale,
    normalize_locale,
    translate,
)
from services.locale_middleware import set_locale_cookie
from services.request_models import LocalePreferenceUpdateRequest
from services.runtime_config import get_session_same_site, is_production_env
from services.web import jsonify, require_json_dict, validate_payload_model

from . import chat_bp


logger = logging.getLogger(__name__)


def _require_user_id(request: Request) -> tuple[int | None, Any]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None, jsonify(
            {"error": translate("common.login_required", locale=get_request_locale(request))},
            status_code=401,
        )
    return int(user_id), None


async def _load_explicit_locale(request: Request, user_id: int):
    session_locale = normalize_locale(request.session.get(PREFERRED_LOCALE_SESSION_KEY))
    if session_locale is not None:
        return session_locale
    if request.session.get(PREFERRED_LOCALE_LOADED_SESSION_KEY) is True:
        return None

    preferred_locale = await get_user_preferred_locale(user_id)
    request.session[PREFERRED_LOCALE_LOADED_SESSION_KEY] = True
    if preferred_locale is not None:
        request.session[PREFERRED_LOCALE_SESSION_KEY] = preferred_locale
    return preferred_locale


@chat_bp.get("/api/user/preferences", name="chat.get_user_preferences")
async def get_user_preferences(request: Request):
    user_id, error_response = _require_user_id(request)
    if error_response is not None:
        return error_response

    try:
        preferred_locale = await _load_explicit_locale(request, user_id)
    except Exception:
        logger.exception("Failed to load user locale preference.")
        return jsonify(
            {"error": translate("preferences.load_failed", locale=get_request_locale(request))},
            status_code=500,
        )
    if preferred_locale is not None:
        request.state.locale = preferred_locale
        request.state.persist_locale_cookie = True
    return jsonify({"locale": preferred_locale or get_request_locale(request)})


@chat_bp.put("/api/user/preferences", name="chat.update_user_preferences")
async def update_user_preferences(request: Request):
    user_id, error_response = _require_user_id(request)
    if error_response is not None:
        return error_response

    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        LocalePreferenceUpdateRequest,
        error_message=translate("preferences.invalid_locale", locale=get_request_locale(request)),
    )
    if validation_error is not None:
        return validation_error

    try:
        updated = await update_user_preferred_locale(user_id, payload.locale)
    except Exception:
        logger.exception("Failed to update user locale preference.")
        return jsonify(
            {"error": translate("preferences.update_failed", locale=get_request_locale(request))},
            status_code=500,
        )
    if not updated:
        return jsonify(
            {"error": translate("preferences.user_not_found", locale=get_request_locale(request))},
            status_code=404,
        )

    # DB成功後にだけセッションとCookieを更新し、失敗時に保存先が食い違わないようにする。
    # Update session/cookie only after DB success so failed writes cannot split state.
    request.session[PREFERRED_LOCALE_SESSION_KEY] = payload.locale
    request.session[PREFERRED_LOCALE_LOADED_SESSION_KEY] = True
    request.state.locale = payload.locale
    request.state.persist_locale_cookie = True
    response = jsonify({"locale": payload.locale})
    set_locale_cookie(
        response,
        payload.locale,
        same_site=get_session_same_site(),
        https_only=is_production_env(),
    )
    return response
