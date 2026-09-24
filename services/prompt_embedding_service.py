"""Background embedding generation for public shared prompts.

The worker reads the prompt text itself instead of receiving it from the caller, so the
text and the ``updated_at`` guard it is stored under always come from the same row
version. If an edit lands while the vector is being generated, the guarded UPDATE
matches nothing, the row keeps the ``pending`` status the edit set, and the edit's own
worker (or the backfill) supplies the vector for the new text.
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


async def embed_prompt(prompt_id: int) -> bool:
    """Read the current text, embed it, and store the vector under the row's guard.

    Returns True when a vector was stored. The provider SDK is synchronous, so the
    generation runs on a thread while each database step stays native async.
    """
    async with session_scope() as session:
        source = await PromptEmbeddingRepository(session).fetch_source(prompt_id)
    if source is None:
        return False
    text = build_prompt_embedding_text(
        str(source.get("title") or ""),
        source.get("description"),
        str(source.get("content") or ""),
        source.get("attributes"),
    )
    if not text.strip():
        return False
    embedding = await asyncio.to_thread(generate_embedding, text)
    if not embedding:
        return False
    async with session_scope() as session, session.begin():
        await PromptEmbeddingRepository(session).store(prompt_id, embedding, source.get("updated_at"))
    return True


def schedule_prompt_embedding(prompt_id: int) -> None:
    """Embed a prompt off the request path.

    Call this after the prompt row is committed: the worker reads through its own
    connection and would not see an uncommitted insert.
    """
    if not embeddings_available():
        return

    def _task() -> None:
        try:
            asyncio.run(embed_prompt(prompt_id))
        except Exception:
            logger.warning("Failed to store embedding for prompt %s", prompt_id, exc_info=True)

    try:
        submit_background_task(_task)
    except Exception:
        logger.warning("Failed to schedule embedding task for prompt %s", prompt_id, exc_info=True)
