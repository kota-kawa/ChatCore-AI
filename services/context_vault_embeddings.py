"""個人コンテキスト（Context Vault）の事実について、埋め込みベクトルをバックグラウンドで生成・保存する。
承認された候補や保存された事実から schedule_embedding が呼ばれる。

Background embedding generation for personal context vault facts.
schedule_embedding is called after a candidate is approved or a fact is saved.
"""

from __future__ import annotations

import asyncio
import logging

from services.background_executor import submit_background_task
from services.db import session_scope
from services.embeddings import (
    EMBEDDING_MAX_INPUT_CHARS,
    embeddings_available,
    generate_embedding,
)
from services.repositories.context_fact_repository import ContextFactRepository

logger = logging.getLogger("blueprints.context_vault")


def build_context_fact_embedding_text(fact_type: str, title: str, content: str) -> str:
    """事実の種類・タイトル・本文を 1 つの埋め込み入力テキストにまとめる（長すぎる分は切り捨てる）。

    Combine a fact's type, title, and body into embedding input text.
    """
    combined = f"種類: {fact_type}\nタイトル: {title}\n{content}"
    return combined[:EMBEDDING_MAX_INPUT_CHARS]


async def _store_embedding(
    fact_id: int,
    embedding: list[float],
    expected_revision: int | None,
) -> None:
    async with session_scope() as session, session.begin():
        await ContextFactRepository(session).store_embedding(
            fact_id,
            embedding,
            expected_revision,
        )


def schedule_embedding(
    fact_id: int,
    fact_type: str,
    title: str,
    content: str,
    expected_revision: int | None = None,
) -> None:
    """リクエストの外で埋め込みを生成し、AsyncSession 経由で保存する。
    埋め込みが使えない設定では何もしない。失敗してもリクエストには影響させず警告ログのみ残す。
    expected_revision は、生成中に事実が更新された場合の古い埋め込みの上書きを防ぐために渡す。

    Generate an embedding off-request and persist it through AsyncSession.
    No-op when embeddings are unavailable; failures only log a warning and never affect the request.
    expected_revision guards against overwriting with a stale embedding if the fact changed meanwhile.
    """
    if not embeddings_available():
        return

    def _task() -> None:
        text = build_context_fact_embedding_text(fact_type, title, content)
        embedding = generate_embedding(text)
        if not embedding:
            return
        try:
            # 日本語: ワーカーは通常のスレッドなので、非同期 DB 書き込み用に短命のイベントループを作る。
            # The executor worker is a plain thread, so create a short-lived
            # event loop for the native async DB write.
            asyncio.run(_store_embedding(fact_id, embedding, expected_revision))
        except Exception:
            logger.warning(
                "Failed to store embedding for context fact %s",
                fact_id,
                exc_info=True,
            )

    try:
        submit_background_task(_task)
    except Exception:
        logger.warning(
            "Failed to schedule embedding task for context fact %s",
            fact_id,
            exc_info=True,
        )
