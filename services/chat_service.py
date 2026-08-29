"""Async Chat use-case services backed by :class:`ChatRepository`."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from .api_errors import ForbiddenOperationError
from .db import is_retryable_db_error, session_scope
from .error_messages import ERROR_DEFAULT_SKILL_IMMUTABLE
from .repositories.chat_repository import (
    DB_RETRY_BACKOFF_SECONDS,
    DB_WRITE_MAX_ATTEMPTS,
    ChatRepository,
)
from .user_skills import (
    build_generative_ui_system_skill,
    is_generative_ui_skill_id,
)

T = TypeVar("T")


@asynccontextmanager
async def _transaction(session: AsyncSession | None, *, write: bool):
    """Yield an isolated session and keep commit/rollback at the service edge."""

    if session is None:
        async with session_scope() as scoped:
            if write:
                async with scoped.begin():
                    yield scoped
            else:
                yield scoped
        return

    # A caller-provided session belongs to the surrounding service/use case.
    # Keeping its transaction open is required when several repository calls
    # are composed into one atomic operation.
    yield session


def _repository(session: AsyncSession, *, token_generator: Callable[[int], str] = secrets.token_urlsafe) -> ChatRepository:
    return ChatRepository(session, token_generator=token_generator)


async def _read(operation: Callable[[ChatRepository], Awaitable[T]], session: AsyncSession | None) -> T:
    async with _transaction(session, write=False) as scoped:
        return await operation(_repository(scoped))


async def _write(
    operation: Callable[[ChatRepository], Awaitable[T]],
    session: AsyncSession | None,
    *,
    token_generator: Callable[[int], str] = secrets.token_urlsafe,
) -> T:
    if session is not None:
        async with _transaction(session, write=True) as scoped:
            return await operation(_repository(scoped, token_generator=token_generator))

    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        try:
            async with _transaction(None, write=True) as scoped:
                return await operation(_repository(scoped, token_generator=token_generator))
        except Exception as exc:
            if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                await asyncio.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise
    raise RuntimeError("Database write retry attempts exhausted.")


async def save_message_to_db(
    chat_room_id: str,
    message: str,
    sender: str,
    attached_file_names: list[str] | None = None,
    parent_id: int | None = None,
    message_parts: list[dict[str, Any]] | None = None,
    attached_file_contents: list[Any] | None = None,
    web_search_context: list[dict[str, Any]] | None = None,
    *,
    session: AsyncSession | None = None,
) -> int | None:
    return await _write(
        lambda repo: repo.save_message(
            chat_room_id,
            message,
            sender,
            attached_file_names,
            parent_id,
            message_parts,
            attached_file_contents,
            web_search_context,
        ),
        session,
    )


async def copy_messages_into_chat_room(
    chat_room_id: str,
    messages: list[dict[str, Any]],
    *,
    session: AsyncSession | None = None,
) -> int:
    return await _write(lambda repo: repo.copy_messages_into_room(chat_room_id, messages), session)


async def get_active_path(
    chat_room_id: str,
    *,
    include_attachment_contents: bool = False,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    return await _read(
        lambda repo: repo.get_active_path(
            chat_room_id,
            include_attachment_contents=include_attachment_contents,
        ),
        session,
    )


async def get_active_leaf_id(chat_room_id: str, *, session: AsyncSession | None = None) -> int | None:
    return await _read(lambda repo: repo.get_active_leaf_id(chat_room_id), session)


async def switch_chat_branch(
    chat_room_id: str,
    target_id: int,
    *,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    return await _write(lambda repo: repo.switch_branch(chat_room_id, target_id), session)


async def create_chat_room_in_db(
    room_id: str,
    user_id: int,
    title: str,
    mode: str = "normal",
    *,
    session: AsyncSession | None = None,
) -> None:
    await _write(lambda repo: repo.create_room(room_id, user_id, title, mode), session)


async def delete_unanswered_user_messages(
    room_id: str,
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> bool:
    return await _write(lambda repo: repo.delete_unanswered_user_messages(room_id, user_id), session)


async def rename_chat_room_in_db(
    room_id: str,
    new_title: str,
    *,
    session: AsyncSession | None = None,
) -> None:
    await _write(lambda repo: repo.rename_room(room_id, new_title), session)


async def rename_chat_room_if_current_title_in(
    room_id: str,
    new_title: str,
    allowed_current_titles: list[str],
    *,
    session: AsyncSession | None = None,
) -> bool:
    return await _write(
        lambda repo: repo.rename_room_if_current_title_in(room_id, new_title, allowed_current_titles),
        session,
    )


async def get_chat_room_messages(
    chat_room_id: str,
    *,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    return await _read(lambda repo: repo.get_room_messages_for_llm(chat_room_id), session)


async def get_room_web_search_contexts(
    chat_room_id: str,
    *,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    return await _read(lambda repo: repo.get_active_path_web_search_contexts(chat_room_id), session)


async def validate_room_owner(
    room_id: str,
    user_id: int,
    forbidden_message: str,
    *,
    session: AsyncSession | None = None,
) -> str | None:
    return await _read(lambda repo: repo.validate_room_owner(room_id, user_id, forbidden_message), session)


async def create_or_get_shared_chat_token(
    room_id: str,
    user_id: int,
    *,
    session: AsyncSession | None = None,
    token_generator: Callable[[int], str] = secrets.token_urlsafe,
) -> str:
    return await _write(
        lambda repo: repo.create_or_get_shared_chat_token(room_id, user_id),
        session,
        token_generator=token_generator,
    )


async def get_shared_chat_room_payload(
    token: str,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    return await _read(lambda repo: repo.get_shared_chat_room_payload(token), session)


async def fork_shared_chat_into_db_room(
    token: str,
    room_id: str,
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Copy a shared conversation in one transaction owned by the caller."""

    async def operation(repo: ChatRepository) -> dict[str, Any]:
        payload = await repo.get_shared_chat_room_payload(token)
        room = payload.get("room") if isinstance(payload, dict) else None
        title = str((room or {}).get("title") or "共有チャット").strip() or "共有チャット"
        messages = [
            message
            for message in (payload.get("messages") if isinstance(payload, dict) else [])
            if isinstance(message, dict)
        ][:500]
        await repo.create_room(room_id, user_id, title, "normal")
        copied = await repo.copy_messages_into_room(room_id, messages)
        return {"id": room_id, "title": title, "mode": "normal", "message_count": copied}

    return await _write(operation, session)


async def get_task_prompt_data(
    task: str,
    user_id: int | None,
    task_id: int | None = None,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    return await _read(lambda repo: repo.get_task_prompt_data(task, user_id, task_id), session)


async def list_chat_rooms(
    user_id: int,
    *,
    limit: int | None = None,
    cursor: tuple[Any, str] | None = None,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    return await _read(lambda repo: repo.list_user_rooms(user_id, limit=limit, cursor=cursor), session)


async def delete_chat_room_for_user(
    room_id: str,
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> dict[str, str]:
    return await _write(lambda repo: repo.delete_room_for_user(room_id, user_id), session)


async def delete_chat_rooms_for_user(
    room_ids: list[str],
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    return await _write(lambda repo: repo.delete_rooms_for_user(room_ids, user_id), session)


async def fetch_chat_history_page(
    chat_room_id: str,
    limit: int,
    before_message_id: int | None = None,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    return await _read(lambda repo: repo.fetch_chat_history_page(chat_room_id, limit, before_message_id), session)


# Project operations are exposed here so Chat blueprints do not reach into the
# legacy synchronous project service.
async def create_project(user_id: int, name: str, instructions: str | None = None, *, session: AsyncSession | None = None):
    return await _write(lambda repo: repo.create_project(user_id, name, instructions), session)


async def list_projects(user_id: int, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.list_projects(user_id), session)


async def get_project(project_id: int, user_id: int, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.get_project(project_id, user_id), session)


async def list_project_rooms(project_id: int, user_id: int, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.list_project_rooms(project_id, user_id), session)


async def update_project(
    project_id: int,
    user_id: int,
    *,
    name: str | None = None,
    instructions: str | None = None,
    session: AsyncSession | None = None,
):
    return await _write(
        lambda repo: repo.update_project(project_id, user_id, name=name, instructions=instructions),
        session,
    )


async def delete_project(project_id: int, user_id: int, *, session: AsyncSession | None = None) -> None:
    await _write(lambda repo: repo.delete_project(project_id, user_id), session)


async def assign_room_to_project(
    room_id: str,
    user_id: int,
    project_id: int | None,
    *,
    session: AsyncSession | None = None,
) -> None:
    await _write(lambda repo: repo.assign_room_to_project(room_id, user_id, project_id), session)


async def get_project_context(room_id: str, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.get_project_context(room_id), session)


async def fetch_tasks(user_id: int | None, locale: str, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.fetch_tasks(user_id, locale), session)


async def list_user_skills(user_id: int, *, session: AsyncSession | None = None):
    async def operation(repo: ChatRepository):
        is_enabled = await repo.get_generative_ui_skill_enabled(user_id)
        personal_skills = await repo.list_user_skills(user_id)
        return [
            build_generative_ui_system_skill(is_enabled=is_enabled),
            *personal_skills,
        ]

    return await _read(operation, session)


async def list_enabled_user_skills(user_id: int, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.list_enabled_user_skills(user_id), session)


async def create_user_skill(
    user_id: int,
    name: str,
    instructions: str,
    *,
    session: AsyncSession | None = None,
):
    return await _write(
        lambda repo: repo.create_user_skill(user_id, name, instructions),
        session,
    )


async def set_user_skill_enabled(
    user_id: int,
    skill_id: int,
    is_enabled: bool,
    *,
    session: AsyncSession | None = None,
):
    if is_generative_ui_skill_id(skill_id):
        next_enabled = bool(is_enabled)
        stored_enabled = await _write(
            lambda repo: repo.set_generative_ui_skill_enabled(user_id, next_enabled),
            session,
        )
        return build_generative_ui_system_skill(is_enabled=stored_enabled)
    return await _write(
        lambda repo: repo.set_user_skill_enabled(user_id, skill_id, is_enabled),
        session,
    )


async def delete_user_skill(
    user_id: int,
    skill_id: int,
    *,
    session: AsyncSession | None = None,
) -> None:
    if is_generative_ui_skill_id(skill_id):
        raise ForbiddenOperationError(
            ERROR_DEFAULT_SKILL_IMMUTABLE,
            code="default_skill_immutable",
        )
    await _write(lambda repo: repo.delete_user_skill(user_id, skill_id), session)


async def update_tasks_order(user_id: int, new_order: list[int], *, session: AsyncSession | None = None) -> None:
    await _write(lambda repo: repo.update_tasks_order(user_id, new_order), session)


async def delete_task(user_id: int, task_id: int, *, session: AsyncSession | None = None) -> None:
    await _write(lambda repo: repo.delete_task(user_id, task_id), session)


async def edit_task(
    user_id: int,
    task_id: int,
    new_task: str,
    prompt_template: str | None,
    response_rules: str | None,
    output_skeleton: str | None,
    input_examples: str | None,
    output_examples: str | None,
    *,
    session: AsyncSession | None = None,
) -> bool:
    return await _write(
        lambda repo: repo.edit_task(
            user_id,
            task_id,
            new_task,
            prompt_template,
            response_rules,
            output_skeleton,
            input_examples,
            output_examples,
        ),
        session,
    )


async def add_task(
    user_id: int,
    title: str,
    prompt_content: str,
    response_rules: str,
    output_skeleton: str,
    input_examples: str,
    output_examples: str,
    *,
    session: AsyncSession | None = None,
) -> None:
    await _write(
        lambda repo: repo.add_task(
            user_id,
            title,
            prompt_content,
            response_rules,
            output_skeleton,
            input_examples,
            output_examples,
        ),
        session,
    )


async def list_room_memory_facts(chat_room_id: str, *, limit: int = 8, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.list_room_memory_facts(chat_room_id, limit=limit), session)


async def get_room_summary(chat_room_id: str, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.get_room_summary(chat_room_id), session)


async def update_user_profile(
    user_id: int,
    *,
    username: str,
    bio: str,
    avatar_url: str | None,
    llm_profile_context: str,
    session: AsyncSession | None = None,
) -> bool:
    return await _write(
        lambda repo: repo.update_user_profile(
            user_id,
            username=username,
            bio=bio,
            avatar_url=avatar_url,
            llm_profile_context=llm_profile_context,
        ),
        session,
    )


async def commit_email_change(user_id: int, new_email: str, *, session: AsyncSession | None = None) -> bool:
    return await _write(lambda repo: repo.commit_email_change(user_id, new_email), session)


async def get_user_by_id(user_id: int, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.get_user_by_id(user_id), session)


async def get_user_by_email(email: str, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.get_user_by_email(email), session)


async def get_user_preferred_locale(user_id: int, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.get_user_preferred_locale(user_id), session)


async def update_user_preferred_locale(user_id: int, locale: str, *, session: AsyncSession | None = None) -> bool:
    return await _write(lambda repo: repo.update_user_preferred_locale(user_id, locale), session)
