"""SQLAlchemy queries used by the embedding backfill command."""

from __future__ import annotations

import json
from typing import Any, ClassVar

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import ContextFact, MemoEntry, Prompt


class EmbeddingBackfillRepository:
    """Read missing vectors and persist regenerated values."""

    # (entity, text columns, row filter). Only public, live prompts are ever searched, so
    # private and soft-deleted rows are left out instead of paying for vectors nobody reads.
    _TABLE_SPECS: ClassVar[dict[str, tuple[Any, tuple[Any, ...], tuple[Any, ...]]]] = {
        "memo_entries": (MemoEntry, (MemoEntry.title, MemoEntry.ai_response), ()),
        "context_facts": (
            ContextFact,
            (ContextFact.fact_type, ContextFact.title, ContextFact.content),
            (),
        ),
        "prompts": (
            Prompt,
            (Prompt.title, Prompt.description, Prompt.content, Prompt.attributes),
            (Prompt.is_public.is_(True), Prompt.deleted_at.is_(None)),
        ),
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @classmethod
    def _table_spec(cls, table: str):
        try:
            return cls._TABLE_SPECS[table]
        except KeyError as exc:
            raise ValueError(f"Unsupported backfill table: {table}") from exc

    async def fetch_batch(
        self,
        table: str,
        *,
        after_id: int,
        include_existing: bool,
        batch_size: int,
    ) -> list[tuple[Any, ...]]:
        model, fields, row_filter = self._table_spec(table)
        statement = (
            select(model.id, *fields)
            .where(model.id > after_id, *row_filter)
            .order_by(model.id)
            .limit(batch_size)
        )
        if not include_existing:
            statement = statement.where(
                or_(
                    model.embedding_vector.is_(None),
                    model.embedding_status == "pending",
                )
            )
        result = await self.session.execute(statement)
        return [tuple(row) for row in result.all()]

    async def count_pending(self, table: str, *, include_existing: bool) -> int:
        model, _, row_filter = self._table_spec(table)
        statement = select(func.count()).select_from(model).where(*row_filter)
        if not include_existing:
            statement = statement.where(
                or_(
                    model.embedding_vector.is_(None),
                    model.embedding_status == "pending",
                )
            )
        return int(await self.session.scalar(statement) or 0)

    async def store_embedding(self, table: str, row_id: int, embedding: list[float]) -> None:
        model, _, _ = self._table_spec(table)
        values: dict[str, Any] = {
            "embedding_vector": [float(value) for value in embedding],
            "embedding_status": "ready",
        }
        if model is MemoEntry:
            values["embedding"] = json.dumps(embedding)
        await self.session.execute(update(model).where(model.id == row_id).values(**values))
