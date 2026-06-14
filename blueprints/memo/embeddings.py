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


# 日本語: get db connection の取得処理を担当します。
# English: Handle fetching for get db connection.
def _get_db_connection():
    memo_module = sys.modules.get("blueprints.memo")
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if memo_module is not None:
        return getattr(memo_module, "get_db_connection", default_get_db_connection)()
    return default_get_db_connection()


# 日本語: store embedding に関する処理の入口です。
# English: Entry point for logic related to store embedding.
def store_embedding(memo_id: int, embedding: list[float]) -> None:
    connection = None
    cursor = None
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
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


# 日本語: schedule embedding に関する処理の入口です。
# English: Entry point for logic related to schedule embedding.
def schedule_embedding(memo_id: int, title: str, ai_response: str) -> None:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not embeddings_available():
        return

    # 日本語: task に関する処理の入口です。
    # English: Entry point for logic related to task.
    def _task() -> None:
        text = build_memo_embedding_text(title, ai_response)
        embedding = generate_embedding(text)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if embedding:
            store_embedding(memo_id, embedding)

    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        get_background_executor().submit(_task)
    except Exception:
        logger.warning("Failed to schedule embedding task for memo %s", memo_id, exc_info=True)
