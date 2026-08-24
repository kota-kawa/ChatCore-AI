"""SQLAlchemy persistence for public prompt view counters."""

from __future__ import annotations

from sqlalchemy import literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import Prompt, PromptViewCount


class PromptViewRepository:
    """Record prompt views without mutating prompts or their revision history."""

    async def increment_public_view(
        self,
        session: AsyncSession,
        prompt_id: int,
    ) -> int | None:
        """Atomically increment an active public prompt and return its new count."""
        insert_statement = pg_insert(PromptViewCount).from_select(
            [PromptViewCount.prompt_id, PromptViewCount.view_count],
            select(Prompt.id, literal(1)).where(
                Prompt.id == int(prompt_id),
                Prompt.is_public.is_(True),
                Prompt.deleted_at.is_(None),
            ),
        )
        statement = insert_statement.on_conflict_do_update(
            index_elements=[PromptViewCount.prompt_id],
            set_={"view_count": PromptViewCount.view_count + 1},
        ).returning(PromptViewCount.view_count)
        result = await session.execute(statement)
        return result.scalar_one_or_none()
