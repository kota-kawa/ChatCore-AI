from __future__ import annotations

from typing import Any

from .db import get_db_connection, is_retryable_db_error, rollback_connection
from .repositories.project_repository import ProjectRepository


# プロジェクトリポジトリのインスタンスを作成して返す
# Create and return an instance of the ProjectRepository
def _get_project_repository() -> ProjectRepository:
    return ProjectRepository(
        connection_getter=get_db_connection,
        retryable_error_checker=is_retryable_db_error,
        rollback=rollback_connection,
    )


def create_project(user_id: int, name: str, instructions: str | None = None) -> dict[str, Any]:
    return _get_project_repository().create_project(user_id, name, instructions)


def list_projects(user_id: int) -> list[dict[str, Any]]:
    return _get_project_repository().list_projects(user_id)


def get_project(project_id: int, user_id: int) -> dict[str, Any]:
    return _get_project_repository().get_project(project_id, user_id)


def update_project(
    project_id: int,
    user_id: int,
    *,
    name: str | None = None,
    instructions: str | None = None,
) -> dict[str, Any]:
    return _get_project_repository().update_project(
        project_id, user_id, name=name, instructions=instructions
    )


def delete_project(project_id: int, user_id: int) -> None:
    return _get_project_repository().delete_project(project_id, user_id)


def assign_room_to_project(room_id: str, user_id: int, project_id: int | None) -> None:
    return _get_project_repository().assign_room_to_project(room_id, user_id, project_id)


def list_project_rooms(project_id: int, user_id: int) -> list[dict[str, Any]]:
    return _get_project_repository().list_project_rooms(project_id, user_id)


def get_project_context(room_id: str) -> dict[str, Any] | None:
    return _get_project_repository().get_project_context(room_id)
