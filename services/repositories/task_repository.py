"""Async SQLAlchemy persistence boundary for user task templates.

Tasks are the reusable prompt templates listed on the chat top page.  Rows with
user_id IS NULL are the bundled catalog, and system_task_key links a
user row back to the bundled definition so localized copy stays in sync until
the user customizes it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.default_tasks import localize_system_task, resolve_system_task_key
from services.error_messages import (
    ERROR_TASK_NAME_CONFLICT,
    ERROR_TASK_NOT_FOUND,
    ERROR_TASK_ORDER_INVALID,
)
from services.i18n import get_current_locale
from services.models import Task
from services.share_common import is_unique_violation

TASK_WRITE_LOCK_NAMESPACE = 1_413_567_307


class TaskRepository:
    """Repository for the bundled and user-owned task templates.

    The repository never commits.  Services own the transaction and pass an
    isolated AsyncSession for one unit of work.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Tasks ------------------------------------------------------------------

    async def fetch_tasks(self, user_id: int | None, locale: str) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(Task)
                .where(Task.user_id == user_id, Task.deleted_at.is_(None))
                .order_by(func.coalesce(Task.display_order, 99999), Task.id)
            )
        ).scalars().all()
        return [self._localize_task(task, locale, is_default=False) for task in rows]

    async def get_task_prompt_data(
        self, task: str, user_id: int | None, task_id: int | None = None
    ) -> dict[str, Any] | None:
        columns = (
            Task.id.label("task_id"),
            Task.system_task_key,
            Task.system_task_revision,
            Task.is_system_task_customized,
            Task.name,
            Task.prompt_template,
            Task.response_rules,
            Task.output_skeleton,
            Task.input_examples,
            Task.output_examples,
        )
        if task_id is not None:
            stmt = select(*columns).where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
        else:
            key = resolve_system_task_key(task)
            lookup_column = Task.system_task_key if key is not None else Task.name
            stmt = select(*columns).where(lookup_column == (key or task), Task.deleted_at.is_(None))
            if user_id:
                stmt = stmt.where(or_(Task.user_id == user_id, Task.user_id.is_(None))).order_by(
                    case((Task.user_id == user_id, 0), else_=1), Task.id
                )
            else:
                stmt = stmt.where(Task.user_id.is_(None)).order_by(Task.id)
            stmt = stmt.limit(1)
        row = (await self.session.execute(stmt)).mappings().first()
        return localize_system_task(dict(row), get_current_locale()) if row is not None else None

    async def update_tasks_order(self, user_id: int, new_order: list[int]) -> None:
        await self._lock_user_tasks(user_id)
        rows = (
            await self.session.execute(
                select(Task.id).where(Task.user_id == user_id, Task.deleted_at.is_(None)).with_for_update()
            )
        ).all()
        active_ids = {int(task_id) for (task_id,) in rows}
        if len(new_order) != len(active_ids) or set(new_order) != active_ids:
            raise ApiServiceError(ERROR_TASK_ORDER_INVALID, 400, code="invalid_task_order")
        for index, task_id in enumerate(new_order):
            result = await self.session.execute(
                update(Task)
                .where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
                .values(display_order=index, updated_at=func.current_timestamp())
            )
            if result.rowcount != 1:
                raise ApiServiceError(ERROR_TASK_ORDER_INVALID, 400, code="invalid_task_order")

    async def delete_task(self, user_id: int, task_id: int) -> None:
        await self._lock_user_tasks(user_id)
        result = await self.session.execute(
            update(Task)
            .where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
            .values(deleted_at=func.current_timestamp(), updated_at=func.current_timestamp())
        )
        if result.rowcount != 1:
            raise ResourceNotFoundError(ERROR_TASK_NOT_FOUND, code="task_not_found")

    async def edit_task(
        self,
        user_id: int,
        task_id: int,
        new_task: str,
        prompt_template: str | None,
        response_rules: str | None,
        output_skeleton: str | None,
        input_examples: str | None,
        output_examples: str | None,
    ) -> bool:
        await self._lock_user_tasks(user_id)
        task = (
            await self.session.execute(
                select(Task)
                .where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if task is None:
            raise ResourceNotFoundError(ERROR_TASK_NOT_FOUND, code="task_not_found")
        duplicate = await self.session.scalar(
            select(Task.id)
            .where(
                Task.user_id == user_id,
                Task.id != task_id,
                Task.deleted_at.is_(None),
                func.lower(func.btrim(Task.name)) == func.lower(func.btrim(new_task)),
            )
            .limit(1)
        )
        if duplicate is not None:
            raise ApiServiceError(ERROR_TASK_NAME_CONFLICT, 409, code="task_name_conflict")
        task.name = new_task
        for field, value in (
            ("prompt_template", prompt_template),
            ("response_rules", response_rules),
            ("output_skeleton", output_skeleton),
            ("input_examples", input_examples),
            ("output_examples", output_examples),
        ):
            if value is not None:
                setattr(task, field, value)
        if task.system_task_key is not None:
            task.is_system_task_customized = True
        await self.session.flush()
        return True

    async def add_task(
        self,
        user_id: int,
        title: str,
        prompt_content: str,
        response_rules: str,
        output_skeleton: str,
        input_examples: str,
        output_examples: str,
    ) -> None:
        await self._lock_user_tasks(user_id)
        duplicate = await self.session.scalar(
            select(Task.id)
            .where(
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
                func.lower(func.btrim(Task.name)) == func.lower(func.btrim(title)),
            )
            .limit(1)
        )
        if duplicate is not None:
            raise ApiServiceError(ERROR_TASK_NAME_CONFLICT, 409, code="task_name_conflict")
        next_order = await self.session.scalar(
            select(func.coalesce(func.max(Task.display_order), -1) + 1).where(
                Task.user_id == user_id, Task.deleted_at.is_(None)
            )
        )
        self.session.add(
            Task(
                user_id=user_id,
                name=title,
                prompt_template=prompt_content,
                response_rules=response_rules,
                output_skeleton=output_skeleton,
                input_examples=input_examples,
                output_examples=output_examples,
                display_order=int(next_order or 0),
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if is_unique_violation(exc):
                raise ApiServiceError(ERROR_TASK_NAME_CONFLICT, 409, code="task_name_conflict") from exc
            raise

    # Internal helpers -------------------------------------------------------

    async def _lock_user_tasks(self, user_id: int) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :user_id)").bindparams(
                namespace=TASK_WRITE_LOCK_NAMESPACE, user_id=user_id
            )
        )

    @staticmethod
    def _localize_task(task: Task, locale: str, *, is_default: bool) -> dict[str, Any]:
        return localize_system_task(
            {
                "task_id": task.id,
                "system_task_key": task.system_task_key,
                "system_task_revision": task.system_task_revision,
                "is_system_task_customized": task.is_system_task_customized,
                "name": task.name,
                "prompt_template": task.prompt_template,
                "response_rules": task.response_rules,
                "output_skeleton": task.output_skeleton,
                "input_examples": task.input_examples,
                "output_examples": task.output_examples,
                "is_default": is_default,
            },
            locale,
        )
