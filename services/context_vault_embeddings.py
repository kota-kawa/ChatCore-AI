"""Background embedding generation for personal context vault facts.

Mirrors ``blueprints/memo/embeddings.py`` but targets the ``context_facts`` table,
reusing the table-agnostic embedding helpers in ``services/memo_ai.py``.
"""

from __future__ import annotations

import logging

from services.background_executor import get_background_executor
from services.memo_ai import EMBEDDING_MAX_INPUT_CHARS, embeddings_available, generate_embedding
from services.repositories.context_fact_repository import ContextFactRepository

logger = logging.getLogger("blueprints.context_vault")


def build_context_fact_embedding_text(fact_type: str, title: str, content: str) -> str:
    """Combine a fact's type, title, and body into the text used for embedding."""
    combined = f"種類: {fact_type}\nタイトル: {title}\n{content}"
    return combined[:EMBEDDING_MAX_INPUT_CHARS]


def schedule_embedding(
    fact_id: int,
    fact_type: str,
    title: str,
    content: str,
    expected_revision: int | None = None,
    *,
    repository: ContextFactRepository | None = None,
) -> None:
    """Schedule a background task to generate and store a fact's embedding vector."""
    if not embeddings_available():
        return

    repo = repository or ContextFactRepository()

    def _task() -> None:
        text = build_context_fact_embedding_text(fact_type, title, content)
        embedding = generate_embedding(text)
        if embedding:
            try:
                repo.store_embedding(fact_id, embedding, expected_revision)
            except Exception:
                logger.warning(
                    "Failed to store embedding for context fact %s", fact_id, exc_info=True
                )

    try:
        get_background_executor().submit(_task)
    except Exception:
        logger.warning(
            "Failed to schedule embedding task for context fact %s", fact_id, exc_info=True
        )
