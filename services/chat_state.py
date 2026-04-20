from __future__ import annotations

import re
import time
from typing import Any

from .chat_context import build_room_summary
from .db import Error, get_db_connection, is_retryable_db_error, rollback_connection
from .datetime_serialization import serialize_datetime_iso

DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05
MAX_MEMORY_FACT_LENGTH = 280
MAX_MEMORY_FACTS_FOR_CONTEXT = 8
_MULTISPACE_PATTERN = re.compile(r"\s+")

_REMEMBER_PATTERN = re.compile(
    r"(?i)(?:^|\n)\s*(?:remember(?: that)?|remember:|覚えて(?:おいて)?[:：]?)(.+)"
)
_NAME_PATTERN = re.compile(r"(?i)\bmy name is\s+([^\n.!?]{1,80})")
_CALL_ME_PATTERN = re.compile(r"(?i)\bcall me\s+([^\n.!?]{1,80})")
_PREFERENCE_PATTERN = re.compile(r"(?i)\bi prefer\s+([^\n.!?]{1,120})")
_FORMAT_PATTERN = re.compile(
    r"(?:今後は|これからは|以後は)([^\n。！？]{1,120})(?:で|を)?(?:お願いします|してください)?"
)


def _normalize_fact_text(text: str) -> str:
    normalized = text if isinstance(text, str) else str(text)
    normalized = normalized.strip().replace("\r\n", "\n").replace("\r", "\n")
    normalized = _MULTISPACE_PATTERN.sub(" ", normalized)
    return normalized[:MAX_MEMORY_FACT_LENGTH].strip(" .")


def extract_memory_facts(message: str) -> list[str]:
    normalized = message if isinstance(message, str) else str(message)
    facts: list[str] = []

    def _append_fact(value: str) -> None:
        normalized_fact = _normalize_fact_text(value)
        if normalized_fact and normalized_fact not in facts:
            facts.append(normalized_fact)

    for match in _REMEMBER_PATTERN.finditer(normalized):
        _append_fact(match.group(1))

    for match in _NAME_PATTERN.finditer(normalized):
        _append_fact(f"ユーザー名: {match.group(1).strip()}")

    for match in _CALL_ME_PATTERN.finditer(normalized):
        _append_fact(f"希望する呼び名: {match.group(1).strip()}")

    for match in _PREFERENCE_PATTERN.finditer(normalized):
        _append_fact(f"ユーザーの好み: {match.group(1).strip()}")

    for match in _FORMAT_PATTERN.finditer(normalized):
        _append_fact(f"回答スタイルの希望: {match.group(1).strip()}")

    return facts


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


def list_room_memory_fact_records(
    chat_room_id: str,
    *,
    limit: int = MAX_MEMORY_FACTS_FOR_CONTEXT,
) -> list[dict[str, Any]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, fact, scope, updated_at
              FROM memory_facts
             WHERE chat_room_id = %s
               AND is_active = TRUE
             ORDER BY updated_at DESC, id DESC
             LIMIT %s
            """,
            (chat_room_id, limit),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "fact": row[1],
                "scope": row[2],
                "updated_at": serialize_datetime_iso(row[3]),
            }
            for row in rows
        ]
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


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


def rebuild_room_summary(chat_room_id: str, messages: list[dict[str, str]]) -> str:
    summary_text, archived_count = build_room_summary(messages)

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
