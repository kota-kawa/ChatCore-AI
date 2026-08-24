"""Embedding generation and asynchronous memo vector persistence."""

from __future__ import annotations

import asyncio
import logging

from services.background_executor import get_background_executor
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
    """Persist one vector in a short-lived native async transaction."""
    if not embedding:
        return
    async with session_scope() as session:
        async with session.begin():
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
    """Generate an embedding off the request path and store it asynchronously."""
    if not embeddings_available():
        return

    def _task() -> None:
        try:
            embedding = generate_embedding(build_memo_embedding_text(title, ai_response))
            if embedding:
                asyncio.run(store_memo_embedding(memo_id, embedding, expected_revision))
        except Exception:
            logger.warning("Failed to store embedding for memo %s", memo_id, exc_info=True)

    try:
        get_background_executor().submit(_task)
    except Exception:
        logger.warning("Failed to schedule embedding task for memo %s", memo_id, exc_info=True)
