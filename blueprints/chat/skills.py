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


def _authenticated_user_id(request: Request) -> int | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


@chat_bp.get("/api/skills", name="chat.list_user_skills")
async def get_user_skills(request: Request):
    user_id = _authenticated_user_id(request)
    if user_id is None:
        return jsonify({"error": ERROR_LOGIN_REQUIRED}, status_code=403)

    try:
        return jsonify({"skills": await list_user_skills(user_id)})
    except Exception:
        return log_and_internal_server_error(logger, "Failed to load user skills.")


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
