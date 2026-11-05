"""埋め込みベクトルの一括再生成(バックフィル)コマンドが使うクエリ。対象はメモ・コンテキスト事実・公開プロンプト。

scripts/backfill_embeddings.py から使われる。

SQLAlchemy queries used by the embedding backfill command.
Used by scripts/backfill_embeddings.py.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import ContextFact, MemoEntry, Prompt


class EmbeddingBackfillRepository:
    """ベクトルが未生成の行を読み出し、再生成した値を保存する。

    Read missing vectors and persist regenerated values.
    """

    # 日本語: 下の定義は (モデル, 埋め込み対象のテキスト列, 行の絞り込み条件)。検索に使われない行(非公開・削除済みのプロンプト、
    # ゴミ箱のメモ)は、誰も読まないベクトルの生成コストを払わないよう対象外にする。復元されたメモは次回の実行で拾われる。

    # 検索対象の公開・有効な投稿だけを埋め込む。ゴミ箱内メモも除き、復元後の実行で補う。
    # (entity, text columns, row filter). Only public, live prompts are ever searched, so
    # private and soft-deleted rows are left out instead of paying for vectors nobody reads.
    # Trashed memos are skipped the same way; a restored one is picked up by the next run.
    _TABLE_SPECS: ClassVar[dict[str, tuple[Any, tuple[Any, ...], tuple[Any, ...]]]] = {
        "memo_entries": (MemoEntry, (MemoEntry.title, MemoEntry.ai_response), (MemoEntry.deleted_at.is_(None),)),
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

    # 日本語: id 昇順のキーセットで 1 バッチ分を返す。include_existing=False のときは、ベクトルが無い行か再生成待ち(pending)の行だけにする。
    # English: Returns one batch in id order (keyset on after_id); unless include_existing, only rows with no vector or a pending status.
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

    # 日本語: ベクトルを保存して ready にする。メモだけは旧形式の JSON 列(embedding)にも同じ値を書く。
    # English: Stores the vector and marks it ready; memo entries also get the same value in the legacy JSON column (embedding).
    async def store_embedding(self, table: str, row_id: int, embedding: list[float]) -> None:
        model, _, _ = self._table_spec(table)
        values: dict[str, Any] = {
            "embedding_vector": [float(value) for value in embedding],
            "embedding_status": "ready",
        }
        if model is MemoEntry:
            values["embedding"] = json.dumps(embedding)
        await self.session.execute(update(model).where(model.id == row_id).values(**values))
