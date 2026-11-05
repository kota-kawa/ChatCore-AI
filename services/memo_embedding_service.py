"""メモの埋め込みベクトルを、リクエストとは別の背景処理で生成して保存する。

メモの作成・更新の後に `schedule_embedding` が呼ばれ、意味検索のためのベクトルを非同期に保存する。
Generates memo embedding vectors in a background task, off the request path, and persists them.
`schedule_embedding` is called after a memo is created or updated, storing the vector used for semantic search.
"""

from __future__ import annotations

import asyncio
import logging

from services.background_executor import submit_background_task
from services.db import session_scope
from services.embeddings import embeddings_available, generate_embedding
from services.memo_ai import build_memo_embedding_text
from services.repositories.memo_embedding_repository import MemoEmbeddingRepository

logger = logging.getLogger(__name__)


async def store_memo_embedding(
    memo_id: int,
    embedding: list[float],
    expected_revision: int | None = None,
) -> None:
    """短いネイティブ非同期トランザクションの中で、ベクトルを1件保存する。

    Persist one vector in a short-lived native async transaction.
    """
    if not embedding:
        return
    async with session_scope() as session, session.begin():
        await MemoEmbeddingRepository(session).store(
            memo_id,
            embedding,
            expected_revision,
        )


def schedule_embedding(
    memo_id: int,
    title: str,
    ai_response: str,
    expected_revision: int | None = None,
) -> None:
    """リクエストの経路の外で埋め込みを生成し、非同期に保存する。

    Generate an embedding off the request path and store it asynchronously.
    """
    if not embeddings_available():
        return

    # 背景スレッドで実行される処理。失敗してもメモ本体の保存には影響させず、警告ログだけ残す。
    # expected_revision を渡すのは、保存前にメモが更新されていた場合に古いベクトルで上書きしないため。
    # Runs on a background thread; a failure only logs a warning and never affects saving the memo itself.
    # expected_revision is passed so a vector for an outdated memo does not overwrite a newer one.
    def _task() -> None:
        try:
            embedding = generate_embedding(build_memo_embedding_text(title, ai_response))
            if embedding:
                asyncio.run(store_memo_embedding(memo_id, embedding, expected_revision))
        except Exception:
            logger.warning("Failed to store embedding for memo %s", memo_id, exc_info=True)

    try:
        submit_background_task(_task)
    except Exception:
        logger.warning("Failed to schedule embedding task for memo %s", memo_id, exc_info=True)
