"""Async SQLAlchemy persistence boundary for project-owned data.

Projects group chat rooms, so this repository owns the ``projects`` rows and the
``chat_rooms.project_id`` association.  Room ownership is verified through
:mod:`services.repositories.chat_room_access` so the chat and project boundaries
keep one locking and error contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.datetime_serialization import serialize_datetime_iso
from services.error_messages import (
    ERROR_CHAT_ROOM_FORBIDDEN,
    ERROR_PROJECT_FORBIDDEN,
    ERROR_PROJECT_NOT_FOUND,
)
from services.models import ChatRoom, Project
from services.repositories.chat_room_access import load_owned_room, serialize_room

DEFAULT_PROJECT_NAME = "新規プロジェクト"
MAX_PROJECT_NAME_LENGTH = 255
MAX_PROJECT_INSTRUCTIONS_LENGTH = 20_000


class ProjectRepository:
    """Repository for projects and their chat room membership.

    The repository never commits.  Services own the transaction and pass an
    isolated ``AsyncSession`` for one unit of work.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_project(
        self,
        user_id: int,
        name: str,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        project = Project(
            user_id=user_id,
            name=self._normalize_name(name),
            instructions=self._normalize_instructions(instructions),
        )
        self.session.add(project)
        await self.session.flush()
        return self._serialize_project(project)

    async def list_projects(self, user_id: int) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(Project, func.count(ChatRoom.id).label("chat_count"))
                .outerjoin(ChatRoom, ChatRoom.project_id == Project.id)
                .where(Project.user_id == user_id)
                .group_by(Project.id)
                .order_by(Project.created_at.desc(), Project.id.desc())
            )
        ).all()
        projects: list[dict[str, Any]] = []
        for project, count in rows:
            payload = self._serialize_project(project)
            payload["chatCount"] = int(count or 0)
            projects.append(payload)
        return projects

    async def get_project(self, project_id: int, user_id: int) -> dict[str, Any]:
        project = await self._owned_project(project_id, user_id)
        payload = self._serialize_project(project)
        payload["rooms"] = await self._project_rooms(project_id)
        return payload

    async def list_project_rooms(self, project_id: int, user_id: int) -> list[dict[str, Any]]:
        await self._owned_project(project_id, user_id)
        return await self._project_rooms(project_id)

    async def update_project(
        self,
        project_id: int,
        user_id: int,
        *,
        name: str | None = None,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        project = await self._owned_project(project_id, user_id, lock=True)
        if name is not None:
            project.name = self._normalize_name(name)
        if instructions is not None:
            project.instructions = self._normalize_instructions(instructions)
        project.updated_at = datetime.utcnow()
        await self.session.flush()
        return self._serialize_project(project)

    async def delete_project(self, project_id: int, user_id: int) -> None:
        await self.session.delete(await self._owned_project(project_id, user_id, lock=True))

    async def assign_room_to_project(self, room_id: str, user_id: int, project_id: int | None) -> None:
        await load_owned_room(self.session, room_id, user_id, ERROR_CHAT_ROOM_FORBIDDEN, lock=True)
        if project_id is not None:
            await self._owned_project(project_id, user_id)
        await self.session.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(project_id=project_id))

    async def get_project_context(self, room_id: str) -> dict[str, Any] | None:
        row = (
            await self.session.execute(
                select(Project.id, Project.name, Project.instructions)
                .join(ChatRoom, ChatRoom.project_id == Project.id)
                .where(ChatRoom.id == room_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return {"project_id": row[0], "name": str(row[1] or ""), "instructions": str(row[2] or "").strip()}

    # Internal helpers -------------------------------------------------------

    async def _project_rooms(self, project_id: int) -> list[dict[str, Any]]:
        rooms = (
            await self.session.execute(
                select(ChatRoom)
                .where(ChatRoom.project_id == project_id)
                .order_by(ChatRoom.last_activity_at.desc(), ChatRoom.id.desc())
            )
        ).scalars().all()
        return [serialize_room(room, project_room=True) for room in rooms]

    async def _owned_project(self, project_id: int, user_id: int, *, lock: bool = False) -> Project:
        statement = select(Project).where(Project.id == project_id)
        if lock:
            statement = statement.with_for_update()
        project = (await self.session.execute(statement)).scalar_one_or_none()
        if project is None:
            raise ResourceNotFoundError(ERROR_PROJECT_NOT_FOUND)
        if project.user_id != user_id:
            raise ForbiddenOperationError(ERROR_PROJECT_FORBIDDEN)
        return project

    @staticmethod
    def _normalize_name(name: Any) -> str:
        return (str(name or "").strip() or DEFAULT_PROJECT_NAME)[:MAX_PROJECT_NAME_LENGTH]

    @staticmethod
    def _normalize_instructions(instructions: Any) -> str | None:
        return None if instructions is None else str(instructions)[:MAX_PROJECT_INSTRUCTIONS_LENGTH]

    @staticmethod
    def _serialize_project(project: Project) -> dict[str, Any]:
        return {
            "id": project.id,
            "name": str(project.name or DEFAULT_PROJECT_NAME),
            "instructions": str(project.instructions or ""),
            "createdAt": serialize_datetime_iso(project.created_at),
            "updatedAt": serialize_datetime_iso(project.updated_at),
        }
