from __future__ import annotations

import json
import logging
import sys

from services.background_executor import get_background_executor
from services.db import get_db_connection as default_get_db_connection
from services.memo_ai import (
    build_memo_embedding_text,
    embeddings_available,
    generate_embedding,
)

logger = logging.getLogger("blueprints.memo")


def _get_db_connection():
    memo_module = sys.modules.get("blueprints.memo")
    if memo_module is not None:
        return getattr(memo_module, "get_db_connection", default_get_db_connection)()
    return default_get_db_connection()


def store_embedding(memo_id: int, embedding: list[float]) -> None:
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE memo_entries SET embedding = %s WHERE id = %s",
            (json.dumps(embedding), memo_id),
        )
        connection.commit()
    except Exception:
        logger.warning("Failed to store embedding for memo %s", memo_id, exc_info=True)
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def schedule_embedding(memo_id: int, title: str, tags: str, ai_response: str) -> None:
    if not embeddings_available():
        return

    def _task() -> None:
        text = build_memo_embedding_text(title, tags, ai_response)
        embedding = generate_embedding(text)
        if embedding:
            store_embedding(memo_id, embedding)

    try:
        get_background_executor().submit(_task)
    except Exception:
        logger.warning("Failed to schedule embedding task for memo %s", memo_id, exc_info=True)
