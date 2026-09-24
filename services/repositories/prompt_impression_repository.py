"""SQLAlchemy persistence for public prompt impression counters."""

from __future__ import annotations

from sqlalchemy import literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import Prompt, PromptImpressionCount


class PromptImpressionRepository:
    """Count how often prompt cards were shown to readers."""

    async def increment_public_impressions(
        self,
        session: AsyncSession,
        prompt_ids: list[int],
    ) -> int:
        """Add one impression to each active public prompt and return how many were counted.

        IDs that are private, deleted, or unknown are dropped by the INSERT ... SELECT, so a
        client cannot create counter rows for prompts nobody can see.
        """
        unique_ids = sorted({int(prompt_id) for prompt_id in prompt_ids})
        if not unique_ids:
            return 0
        insert_statement = pg_insert(PromptImpressionCount).from_select(
            [PromptImpressionCount.prompt_id, PromptImpressionCount.impression_count],
            select(Prompt.id, literal(1)).where(
                Prompt.id.in_(unique_ids),
                Prompt.is_public.is_(True),
                Prompt.deleted_at.is_(None),
            ),
        )
        statement = insert_statement.on_conflict_do_update(
            index_elements=[PromptImpressionCount.prompt_id],
            set_={"impression_count": PromptImpressionCount.impression_count + 1},
        ).returning(PromptImpressionCount.prompt_id)
        result = await session.execute(statement)
        return len(result.scalars().all())
