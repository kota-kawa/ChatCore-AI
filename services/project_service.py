"""Async project operations exposed to the Chat blueprint.

Projects are owned by the Chat repository because assigning a room to a
project is part of the same persistence boundary as chat rooms.  Keeping this
module as a thin async facade preserves the public service import path without
reintroducing the legacy synchronous connection repository.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .chat_service import (
    assign_room_to_project as _assign_room_to_project,
    create_project as _create_project,
    delete_project as _delete_project,
    get_project as _get_project,
    get_project_context as _get_project_context,
    list_project_rooms as _list_project_rooms,
    list_projects as _list_projects,
    update_project as _update_project,
)


async def create_project(
    user_id: int,
    name: str,
    instructions: str | None = None,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    return await _create_project(user_id, name, instructions, session=session)


async def list_projects(user_id: int, *, session: AsyncSession | None = None) -> list[dict[str, Any]]:
    return await _list_projects(user_id, session=session)


async def get_project(
    project_id: int,
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    return await _get_project(project_id, user_id, session=session)


async def update_project(
    project_id: int,
    user_id: int,
    *,
    name: str | None = None,
    instructions: str | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    return await _update_project(
        project_id,
        user_id,
        name=name,
        instructions=instructions,
        session=session,
    )


async def delete_project(
    project_id: int,
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> None:
    await _delete_project(project_id, user_id, session=session)


async def assign_room_to_project(
    room_id: str,
    user_id: int,
    project_id: int | None,
    *,
    session: AsyncSession | None = None,
) -> None:
    await _assign_room_to_project(room_id, user_id, project_id, session=session)


async def list_project_rooms(
    project_id: int,
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    return await _list_project_rooms(project_id, user_id, session=session)


async def get_project_context(room_id: str, *, session: AsyncSession | None = None) -> dict[str, Any] | None:
    return await _get_project_context(room_id, session=session)
