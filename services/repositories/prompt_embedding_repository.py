"""Persistence for public prompt embedding vectors."""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import Prompt


class PromptEmbeddingRepository:
    """Store one prompt vector and mark the row as embedded."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def store(self, prompt_id: int, embedding: list[float]) -> None:
        await self.session.execute(
            update(Prompt)
            .where(Prompt.id == int(prompt_id))
            .values(
                embedding_vector=[float(value) for value in embedding],
                embedding_status="ready",
            )
        )
