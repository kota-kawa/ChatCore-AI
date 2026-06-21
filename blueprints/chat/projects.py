import logging
from typing import Any

from fastapi import Request

from services.api_errors import ApiServiceError
from services.async_utils import run_blocking
from services.error_messages import ERROR_LOGIN_REQUIRED
from services.project_service import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
    assign_room_to_project,
)
from services.request_models import (
    AssignRoomProjectRequest,
    ProjectCreateRequest,
    ProjectIdRequest,
    ProjectUpdateRequest,
)
from services.web import (
    jsonify,
    jsonify_service_error,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

from . import chat_bp

logger = logging.getLogger(__name__)


# ログインユーザーのIDを取得する。未ログインなら 401 レスポンスを返す。
# Resolve the authenticated user id, or return a 401 response for guests.
def _require_user_id(request: Request) -> tuple[int | None, Any]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None, jsonify({"error": ERROR_LOGIN_REQUIRED}, status_code=401)
    return user_id, None


# リクエストボディを取得し、指定モデルで検証する共通ヘルパー。
# Shared helper to read and validate the request body against a model.
async def _read_payload(request: Request, model: Any, error_message: str):
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return None, error_response
    payload, validation_error = validate_payload_model(data, model, error_message=error_message)
    if validation_error is not None:
        return None, validation_error
    return payload, None


@chat_bp.post("/api/projects", name="chat.create_project")
async def create_project_endpoint(request: Request):
    """
    新しいプロジェクトを作成します（ログインユーザーのみ）。
    Create a new project (authenticated users only).
    """
    user_id, error = _require_user_id(request)
    if error is not None:
        return error

    payload, error_response = await _read_payload(request, ProjectCreateRequest, "name is required")
    if error_response is not None:
        return error_response

    try:
        project = await run_blocking(create_project, user_id, payload.name, payload.instructions)
        return jsonify({"project": project}, status_code=201)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to create project.")


@chat_bp.get("/api/projects", name="chat.list_projects")
async def list_projects_endpoint(request: Request):
    """
    ログインユーザーのプロジェクト一覧を返します。
    Return the authenticated user's project list.
    """
    user_id, error = _require_user_id(request)
    if error is not None:
        return error

    try:
        projects = await run_blocking(list_projects, user_id)
        return jsonify({"projects": projects}, status_code=200)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to list projects.")


@chat_bp.get("/api/projects/{project_id}", name="chat.get_project")
async def get_project_endpoint(request: Request, project_id: int):
    """
    プロジェクト詳細（指示・所属チャット）を返します。
    Return project detail including instructions and member chats.
    """
    user_id, error = _require_user_id(request)
    if error is not None:
        return error

    try:
        project = await run_blocking(get_project, project_id, user_id)
        return jsonify({"project": project}, status_code=200)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to get project.")


@chat_bp.post("/api/update_project", name="chat.update_project")
async def update_project_endpoint(request: Request):
    """
    プロジェクトの名前・カスタム指示を更新します。
    Update a project's name and/or custom instructions.
    """
    user_id, error = _require_user_id(request)
    if error is not None:
        return error

    payload, error_response = await _read_payload(request, ProjectUpdateRequest, "project_id is required")
    if error_response is not None:
        return error_response

    try:
        project = await run_blocking(
            update_project,
            payload.project_id,
            user_id,
            name=payload.name,
            instructions=payload.instructions,
        )
        return jsonify({"project": project}, status_code=200)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to update project.")


@chat_bp.post("/api/delete_project", name="chat.delete_project")
async def delete_project_endpoint(request: Request):
    """
    プロジェクトを削除します。配下チャットは残り、未所属になります。
    Delete a project. Its chats survive and become unassigned.
    """
    user_id, error = _require_user_id(request)
    if error is not None:
        return error

    payload, error_response = await _read_payload(request, ProjectIdRequest, "project_id is required")
    if error_response is not None:
        return error_response

    try:
        await run_blocking(delete_project, payload.project_id, user_id)
        return jsonify({"message": "プロジェクトを削除しました。"}, status_code=200)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to delete project.")


@chat_bp.post("/api/assign_room_project", name="chat.assign_room_project")
async def assign_room_project_endpoint(request: Request):
    """
    チャットルームをプロジェクトに所属させる/解除します（project_id=null で解除）。
    Assign a chat room to a project, or unassign it (project_id=null).
    """
    user_id, error = _require_user_id(request)
    if error is not None:
        return error

    payload, error_response = await _read_payload(request, AssignRoomProjectRequest, "room_id is required")
    if error_response is not None:
        return error_response

    try:
        await run_blocking(assign_room_to_project, payload.room_id, user_id, payload.project_id)
        return jsonify({"message": "更新しました。"}, status_code=200)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to assign room to project.")
