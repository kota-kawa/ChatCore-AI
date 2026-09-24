"""Background embedding generation for public shared prompts.

Prompts have no revision counter, so an edit that lands while an older embedding is still
being generated can leave a stale vector marked ready. The edit path resets
``embedding_status`` to ``pending`` before scheduling, and the backfill command treats
``pending`` rows as work, so the stale vector is replaced on the next backfill run.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from services.background_executor import submit_background_task
from services.db import session_scope
from services.embeddings import (
    EMBEDDING_MAX_INPUT_CHARS,
    embeddings_available,
    generate_embedding,
)
from services.repositories.prompt_embedding_repository import PromptEmbeddingRepository

logger = logging.getLogger(__name__)


def build_prompt_embedding_text(
    title: str,
    description: str | None,
    content: str,
    attributes: dict[str, Any] | None = None,
) -> str:
    """Combine the fields a reader sees into one embedding input.

    Skill posts keep their body in ``attributes.skill_markdown`` and leave ``content``
    empty, so the markdown stands in for the body there.
    """
    body = content or ""
    if not body.strip() and isinstance(attributes, dict):
        body = str(attributes.get("skill_markdown") or "")
    parts: list[str] = []
    if title:
        parts.append(f"タイトル: {title}")
    if description:
        parts.append(description)
    if body:
        parts.append(body)
    return "\n".join(parts)[:EMBEDDING_MAX_INPUT_CHARS]


async def store_prompt_embedding(prompt_id: int, embedding: list[float]) -> None:
    """Persist one vector in a short-lived native async transaction."""
    if not embedding:
        return
    async with session_scope() as session, session.begin():
        await PromptEmbeddingRepository(session).store(prompt_id, embedding)


def schedule_prompt_embedding(
    prompt_id: int,
    title: str,
    description: str | None,
    content: str,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Generate an embedding off the request path and store it asynchronously.

    Call this after the prompt row is committed: the worker writes through its own
    connection and would not see an uncommitted insert.
    """
    if not embeddings_available():
        return

    def _task() -> None:
        try:
            embedding = generate_embedding(
                build_prompt_embedding_text(title, description, content, attributes)
            )
            if embedding:
                asyncio.run(store_prompt_embedding(prompt_id, embedding))
        except Exception:
            logger.warning("Failed to store embedding for prompt %s", prompt_id, exc_info=True)

    try:
        submit_background_task(_task)
    except Exception:
        logger.warning("Failed to schedule embedding task for prompt %s", prompt_id, exc_info=True)
