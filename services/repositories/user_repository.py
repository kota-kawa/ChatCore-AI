"""Async SQLAlchemy persistence for account-owned user data."""

from __future__ import annotations

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import (
    ChatRoom,
    MemoEntry,
    MemoryFact,
    Prompt,
    PromptLike,
    Task,
    User,
    UserAuthProvider,
    UserPasskey,
)


class UserRepository:
    """Persistence boundary for account cleanup and default user content."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def delete_account(self, user_id: int) -> bool:
        user = await self.session.scalar(
            select(User)
            .where(User.id == int(user_id))
            .with_for_update()
        )
        if user is None:
            return False

        # These are the explicit deletes from the legacy account workflow.
        # Other user-owned rows use ON DELETE CASCADE from users and are
        # removed by the final ORM delete in the same transaction.
        for model in (
            PromptLike,
            MemoEntry,
            MemoryFact,
            UserAuthProvider,
            UserPasskey,
            ChatRoom,
            Task,
            Prompt,
        ):
            await self.session.execute(
                delete(model).where(model.user_id == int(user_id))
            )

        await self.session.execute(
            delete(User).where(User.id == int(user_id))
        )
        return True

    async def copy_default_tasks(self, user_id: int) -> None:
        """Copy the bundled catalog while retaining the advisory-lock semantics."""

        from services.default_tasks import default_task_rows

        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:user_id)"),
            {"user_id": int(user_id)},
        )
        for (
            system_task_key,
            system_task_revision,
            name,
            prompt_template,
            response_rules,
            output_skeleton,
            input_examples,
            output_examples,
            display_order,
        ) in default_task_rows(include_key=True):
            existing_id = await self.session.scalar(
                select(Task.id)
                .where(
                    Task.user_id == int(user_id),
                    or_(
                        Task.system_task_key == system_task_key,
                        func.lower(func.btrim(Task.name))
                        == func.lower(func.btrim(name)),
                    ),
                )
                .limit(1)
            )
            if existing_id is not None:
                continue

            statement = (
                pg_insert(Task)
                .values(
                    user_id=int(user_id),
                    system_task_key=system_task_key,
                    system_task_revision=system_task_revision,
                    name=name,
                    prompt_template=prompt_template,
                    response_rules=response_rules,
                    output_skeleton=output_skeleton,
                    input_examples=input_examples,
                    output_examples=output_examples,
                    display_order=display_order,
                )
                .on_conflict_do_nothing()
            )
            await self.session.execute(statement)
