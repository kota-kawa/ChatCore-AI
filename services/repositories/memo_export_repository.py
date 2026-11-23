"""メモのエクスポート用の読み取り専用クエリ。

blueprints/memo/export_formats.py などのエクスポート処理が使う。

Read-only memo export queries.
Used by the memo export code such as blueprints/memo/export_formats.py.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.db import in_transaction
from services.models import MemoEntry


# 日本語: ゴミ箱に入っていない自分のメモを新しい順に最大 1000 件返す。memo_ids があればその ID に絞る。
# English: Returns the user's non-trashed memos, newest first, up to 1000; memo_ids narrows the result to those ids.
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
        ).where(MemoEntry.user_id == user_id, MemoEntry.deleted_at.is_(None))
        if memo_ids:
            statement = statement.where(MemoEntry.id.in_(memo_ids))
        rows = (
            await db.execute(
                statement.order_by(MemoEntry.created_at.desc()).limit(1000)
            )
        ).mappings().all()
        return [dict(row) for row in rows]

    return await in_transaction(session, operation)
