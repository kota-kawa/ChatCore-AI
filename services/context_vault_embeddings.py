"""Background embedding generation for personal context vault facts."""

from __future__ import annotations

import asyncio
import logging

from services.background_executor import get_background_executor
from services.db import session_scope
from services.embeddings import (
    EMBEDDING_MAX_INPUT_CHARS,
    embeddings_available,
    generate_embedding,
)
from services.repositories.context_fact_repository import ContextFactRepository

logger = logging.getLogger("blueprints.context_vault")


def build_context_fact_embedding_text(fact_type: str, title: str, content: str) -> str:
    """Combine a fact's type, title, and body into embedding input text."""
    combined = f"種類: {fact_type}\nタイトル: {title}\n{content}"
    return combined[:EMBEDDING_MAX_INPUT_CHARS]


async def _store_embedding(
    fact_id: int,
    embedding: list[float],
    expected_revision: int | None,
) -> None:
    async with session_scope() as session:
        async with session.begin():
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
    """Generate an embedding off-request and persist it through AsyncSession."""
    if not embeddings_available():
        return

    def _task() -> None:
        text = build_context_fact_embedding_text(fact_type, title, content)
        embedding = generate_embedding(text)
        if not embedding:
            return
        try:
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
        get_background_executor().submit(_task)
    except Exception:
        logger.warning(
            "Failed to schedule embedding task for context fact %s",
            fact_id,
            exc_info=True,
        )
