"""メモの埋め込みベクトルを保存する永続化処理。

services/memo_embedding_service.py から使われる。

Persistence for memo embedding vectors.
Used by services/memo_embedding_service.py.
"""

from __future__ import annotations

import json

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import MemoEntry


class MemoEmbeddingRepository:
    """ベクトルを保存する。メモの revision による競合防止を保つ。

    Store vectors while preserving the memo revision guard.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # 日本語: expected_revision を渡すと、ベクトル生成中にメモが編集されていた場合(revision が変わった場
    # 合)は古い内容のベクトルを書き込まない。
    # 旧形式の JSON 列(embedding)と pgvector 列(embedding_vector)の両方に同じ値を書く。
    # English: With expected_revision, a vector computed for an outdated memo (revision changed meanwhile) is not written.
    # The same value goes to both the legacy JSON column (embedding) and the pgvector column (embedding_vector).
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
                embedding_status="ready",
            )
        )
