"""Persistence for memo embedding vectors."""

from __future__ import annotations

import json

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import MemoEntry


class MemoEmbeddingRepository:
    """Store vectors while preserving the memo revision guard."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def store(
        self,
        memo_id: int,
        embedding: list[float],
        expected_revision: int | None = None,
    ) -> None:
        conditions = [MemoEntry.id == memo_id]
        if expected_revision is not None:
            conditions.append(MemoEntry.revision == expected_revision)
        await self.session.execute(
            update(MemoEntry)
            .where(*conditions)
            .values(
                embedding=json.dumps([float(value) for value in embedding]),
                embedding_vector=[float(value) for value in embedding],
            )
        )
