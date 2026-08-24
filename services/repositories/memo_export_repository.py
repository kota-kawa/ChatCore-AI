"""Read-only memo export queries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.db import session_scope
from services.models import MemoEntry

T = TypeVar("T")


async def _in_transaction(
    session: AsyncSession | None,
    operation: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    if session is not None:
        return await operation(session)
    async with session_scope() as owned_session:
        async with owned_session.begin():
            return await operation(owned_session)


async def fetch_memos_for_export(
    user_id: int,
    memo_ids: list[int] | None,
    *,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    async def operation(db: AsyncSession) -> list[dict[str, Any]]:
        statement = select(
            MemoEntry.id,
            MemoEntry.title,
            MemoEntry.ai_response,
            MemoEntry.background_color,
            MemoEntry.created_at,
            MemoEntry.updated_at,
        ).where(MemoEntry.user_id == user_id)
        if memo_ids:
            statement = statement.where(MemoEntry.id.in_(memo_ids))
        rows = (
            await db.execute(
                statement.order_by(MemoEntry.created_at.desc()).limit(1000)
            )
        ).mappings().all()
        return [dict(row) for row in rows]

    return await _in_transaction(session, operation)
