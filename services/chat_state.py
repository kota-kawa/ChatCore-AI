from __future__ import annotations

import time
from typing import Any

from .chat_summary import build_room_summary_text
from .db import Error, get_db_connection, is_retryable_db_error, rollback_connection
from .datetime_serialization import serialize_datetime_iso
from .memory_extraction import extract_memory_facts

DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05
MAX_MEMORY_FACTS_FOR_CONTEXT = 8

__all__ = [
    "extract_memory_facts",
    "get_room_summary",
    "list_room_memory_facts",
    "rebuild_room_summary",
    "remember_facts_from_message",
]


# チャットルームに紐づくアクティブな記憶事実のテキストリストを取得する
# Retrieve the text list of active memory facts associated with the chat room
def list_room_memory_facts(chat_room_id: str, *, limit: int = MAX_MEMORY_FACTS_FOR_CONTEXT) -> list[str]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT fact
              FROM memory_facts
             WHERE chat_room_id = %s
               AND scope = 'room'
               AND is_active = TRUE
             ORDER BY updated_at DESC, id DESC
             LIMIT %s
            """,
            (chat_room_id, limit),
        )
        rows = cursor.fetchall()
        return [str(row[0]) for row in rows if row and row[0]]
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# メッセージから記憶事実を抽出してデータベースに保存（既存なら更新）する
# Extract memory facts from the message and save (or update if existing) them in the database
def remember_facts_from_message(
    chat_room_id: str,
    user_id: int,
    message: str,
    *,
    source_message_id: int | None = None,
) -> list[str]:
    facts = extract_memory_facts(message)
    if not facts:
        return []

    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            for fact in facts:
                cursor.execute(
                    """
                    SELECT id
                      FROM memory_facts
                     WHERE chat_room_id = %s
                       AND scope = 'room'
                       AND lower(fact) = lower(%s)
                     LIMIT 1
                    """,
                    (chat_room_id, fact),
                )
                existing = cursor.fetchone()
                if existing:
                    cursor.execute(
                        """
                        UPDATE memory_facts
                           SET fact = %s,
                               user_id = %s,
                               source_message_id = COALESCE(%s, source_message_id),
                               is_active = TRUE,
                               updated_at = CURRENT_TIMESTAMP
                         WHERE id = %s
                        """,
                        (fact, user_id, source_message_id, existing[0]),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO memory_facts (
                            user_id,
                            chat_room_id,
                            scope,
                            fact,
                            source_message_id
                        )
                        VALUES (%s, %s, 'room', %s, %s)
                        """,
                        (user_id, chat_room_id, fact, source_message_id),
                    )
            conn.commit()
            return facts
        except Error as exc:
            if conn is not None:
                rollback_connection(conn)
            if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                time.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise
        except BaseException:
            if conn is not None:
                rollback_connection(conn)
            raise
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    return facts


# チャットルームの要約情報を取得する
# Retrieve the summary information of the chat room
def get_room_summary(chat_room_id: str) -> dict[str, Any] | None:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT summary, archived_message_count, updated_at
              FROM chat_room_summaries
             WHERE chat_room_id = %s
            """,
            (chat_room_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "summary": row[0] or "",
            "archived_message_count": int(row[1] or 0),
            "updated_at": serialize_datetime_iso(row[2]),
        }
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# メッセージ履歴からチャットルームの要約を再構築してデータベースに保存（または削除）する
# Rebuild the chat room summary from message history and save (or delete if empty) it in the database
def rebuild_room_summary(
    chat_room_id: str,
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
) -> str:
    # 要約は会話で選択中のモデルに任せる。model 未指定時は決定的な抜粋方式になる。
    # Summarize with the conversation's own model; without one the deterministic
    # excerpt summary is used instead.
    summary_text, archived_count = build_room_summary_text(messages, model=model)

    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            if not summary_text:
                cursor.execute(
                    "DELETE FROM chat_room_summaries WHERE chat_room_id = %s",
                    (chat_room_id,),
                )
                conn.commit()
                return ""

            cursor.execute(
                """
                INSERT INTO chat_room_summaries (
                    chat_room_id,
                    summary,
                    archived_message_count
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (chat_room_id)
                DO UPDATE
                    SET summary = EXCLUDED.summary,
                        archived_message_count = EXCLUDED.archived_message_count,
                        updated_at = CURRENT_TIMESTAMP
                """,
                (chat_room_id, summary_text, archived_count),
            )
            conn.commit()
            return summary_text
        except Error as exc:
            if conn is not None:
                rollback_connection(conn)
            if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                time.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise
        except BaseException:
            if conn is not None:
                rollback_connection(conn)
            raise
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    return summary_text
