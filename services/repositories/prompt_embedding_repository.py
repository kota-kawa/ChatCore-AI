"""公開プロンプトの埋め込みベクトルの元テキスト取得と保存。

services/prompt_embedding_service.py から使われる。

Persistence for public prompt embedding vectors.
Used by services/prompt_embedding_service.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import Prompt


class PromptEmbeddingRepository:
    """埋め込み対象のテキストを読み出し、``updated_at`` を条件にベクトルを保存する。

    プロンプトには revision が無いため、編集のたびに更新される ``updated_at`` がその代わりになる。
    テキストを読んだ時点の ``updated_at`` のままの行にだけ保存するので、遅れて終わった古い生成が新しい編集のベクトルを上書きしない。

    Read the text to embed and store the vector under an ``updated_at`` guard.

    Prompts carry no revision counter, so ``updated_at`` (bumped by every edit) plays the
    role that ``revision`` plays for memos: a vector is stored only while the row still
    has the ``updated_at`` its text was read with, so a slower, older generation can never
    overwrite the vector of a later edit.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def fetch_source(self, prompt_id: int) -> dict[str, Any] | None:
        """公開中で削除されていないプロンプトの、埋め込み対象のフィールドを返す(該当しなければ None)。

        Return the embeddable fields of a live public prompt, or None.
        """
        result = await self.session.execute(
            select(
                Prompt.title,
                Prompt.description,
                Prompt.content,
                Prompt.attributes,
                Prompt.updated_at,
            ).where(
                Prompt.id == int(prompt_id),
                Prompt.is_public.is_(True),
                Prompt.deleted_at.is_(None),
            )
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def store(
        self,
        prompt_id: int,
        embedding: list[float],
        expected_updated_at: datetime | None,
    ) -> None:
        conditions = [Prompt.id == int(prompt_id)]
        if expected_updated_at is not None:
            conditions.append(Prompt.updated_at == expected_updated_at)
        await self.session.execute(
            update(Prompt)
            .where(*conditions)
            .values(
                embedding_vector=[float(value) for value in embedding],
                embedding_status="ready",
            )
        )
