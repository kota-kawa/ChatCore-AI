"""Async project repository facade.

Project persistence is implemented by :class:`ChatRepository` so room/project
association changes share the same ownership and transaction rules.  This
module keeps the historical import path for callers that still use a project
repository, but accepts only an ``AsyncSession`` and never opens a connection
or cursor itself.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.repositories.chat_repository import ChatRepository

ERROR_PROJECT_NOT_FOUND = "該当プロジェクトが見つかりません"
ERROR_PROJECT_FORBIDDEN = "他ユーザーのプロジェクトは操作できません"
MAX_PROJECT_NAME_LENGTH = 255
MAX_PROJECT_INSTRUCTIONS_LENGTH = 20_000


class ProjectRepository:
    """Async project persistence boundary using a caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._chat_repository = ChatRepository(session)

    async def create_project(
        self,
        user_id: int,
        name: str,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        return await self._chat_repository.create_project(user_id, name, instructions)

    async def list_projects(self, user_id: int) -> list[dict[str, Any]]:
        return await self._chat_repository.list_projects(user_id)

    async def get_project(self, project_id: int, user_id: int) -> dict[str, Any]:
        return await self._chat_repository.get_project(project_id, user_id)

    async def update_project(
        self,
        project_id: int,
        user_id: int,
        *,
        name: str | None = None,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        return await self._chat_repository.update_project(
            project_id,
            user_id,
            name=name,
            instructions=instructions,
        )

    async def delete_project(self, project_id: int, user_id: int) -> None:
        await self._chat_repository.delete_project(project_id, user_id)

    async def assign_room_to_project(
        self,
        room_id: str,
        user_id: int,
        project_id: int | None,
    ) -> None:
        await self._chat_repository.assign_room_to_project(room_id, user_id, project_id)

    async def list_project_rooms(self, project_id: int, user_id: int) -> list[dict[str, Any]]:
        return await self._chat_repository.list_project_rooms(project_id, user_id)

    async def get_project_context(self, room_id: str) -> dict[str, Any] | None:
        return await self._chat_repository.get_project_context(room_id)
