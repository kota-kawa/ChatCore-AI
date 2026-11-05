"""ユーザー独自の Skill(名前と指示のセット)の一覧・追加・有効/無効の切り替え・削除 API。

ログイン必須で、本人の Skill だけを扱う。実際の保存・検証は services/chat_service.py が担う。

APIs to list, add, enable/disable and delete the user's own Skills (a name plus instructions).
Sign-in is required and only the user's own Skills are touched; persistence and validation live in services/chat_service.py.
"""

import logging

from fastapi import Request

from services.api_errors import ApiServiceError
from services.chat_service import (
    create_user_skill,
    delete_user_skill,
    list_user_skills,
    set_user_skill_enabled,
)
from services.error_messages import ERROR_LOGIN_REQUIRED
from services.request_models import CreateUserSkillRequest, UpdateUserSkillStateRequest
from services.web import (
    jsonify,
    jsonify_service_error,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

from . import chat_bp

logger = logging.getLogger(__name__)


# セッションからログイン中のユーザー ID を整数で返す。未ログインや不正な値は None。
# Return the signed-in user id from the session as an int; None when signed out or the value is invalid.
def _authenticated_user_id(request: Request) -> int | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


# 自分の Skill 一覧を返す。
# List the user's own Skills.
@chat_bp.get("/api/skills", name="chat.list_user_skills")
async def get_user_skills(request: Request):
    user_id = _authenticated_user_id(request)
    if user_id is None:
        return jsonify({"error": ERROR_LOGIN_REQUIRED}, status_code=403)

    try:
        return jsonify({"skills": await list_user_skills(user_id)})
    except Exception:
        return log_and_internal_server_error(logger, "Failed to load user skills.")


# Skill(名前と指示)を新しく追加する。
# Add a new Skill (name and instructions).
@chat_bp.post("/api/skills", name="chat.create_user_skill")
async def add_user_skill(request: Request):
    user_id = _authenticated_user_id(request)
    if user_id is None:
        return jsonify({"error": ERROR_LOGIN_REQUIRED}, status_code=403)

    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        CreateUserSkillRequest,
        error_message="Skill名と指示を入力してください。",
    )
    if validation_error is not None:
        return validation_error

    try:
        skill = await create_user_skill(user_id, payload.name, payload.instructions)
        return jsonify({"skill": skill}, status_code=201)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to create user skill.")


# Skill の有効/無効を切り替える。
# Enable or disable a Skill.
@chat_bp.patch("/api/skills/{skill_id}", name="chat.update_user_skill_state")
async def update_user_skill_state(skill_id: int, request: Request):
    user_id = _authenticated_user_id(request)
    if user_id is None:
        return jsonify({"error": ERROR_LOGIN_REQUIRED}, status_code=403)

    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        UpdateUserSkillStateRequest,
        error_message="is_enabledにはtrueまたはfalseを指定してください。",
    )
    if validation_error is not None:
        return validation_error

    try:
        skill = await set_user_skill_enabled(user_id, skill_id, payload.is_enabled)
        return jsonify({"skill": skill})
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to update user skill.")


# Skill を削除する。
# Delete a Skill.
@chat_bp.delete("/api/skills/{skill_id}", name="chat.delete_user_skill")
async def remove_user_skill(skill_id: int, request: Request):
    user_id = _authenticated_user_id(request)
    if user_id is None:
        return jsonify({"error": ERROR_LOGIN_REQUIRED}, status_code=403)

    try:
        await delete_user_skill(user_id, skill_id)
        return jsonify({"message": "Skillを削除しました。"})
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to delete user skill.")
