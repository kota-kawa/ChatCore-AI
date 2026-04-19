from __future__ import annotations

import secrets
import time
from typing import Any

from .api_errors import ResourceNotFoundError
from .db import Error, get_db_connection, is_retryable_db_error, rollback_connection
from .datetime_serialization import serialize_datetime_iso
from .error_messages import ERROR_MEMO_NOT_FOUND_FOR_SHARE, ERROR_SHARED_LINK_NOT_FOUND

UNIQUE_VIOLATION_PGCODE = "23505"
DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05
SHARED_TOKEN_MAX_COLLISION_RETRIES = 5


def create_or_get_shared_memo_token(memo_id: int, user_id: int) -> str:
    # メモ所有者を検証した上で共有トークンを作成し、既存があれば再利用する
    # Create a memo share token after owner validation and reuse the existing one.
    for _ in range(SHARED_TOKEN_MAX_COLLISION_RETRIES):
        token = secrets.token_urlsafe(18)
        collision_detected = False

        for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
            with get_db_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "SELECT 1 FROM memo_entries WHERE id = %s AND user_id = %s",
                        (memo_id, user_id),
                    )
                    if not cursor.fetchone():
                        raise ResourceNotFoundError(ERROR_MEMO_NOT_FOUND_FOR_SHARE)

                    cursor.execute(
                        """
                        INSERT INTO shared_memo_entries (memo_entry_id, share_token)
                        VALUES (%s, %s)
                        ON CONFLICT (memo_entry_id)
                        DO UPDATE SET memo_entry_id = EXCLUDED.memo_entry_id
                        RETURNING share_token
                        """,
                        (memo_id, token),
                    )
                    row = cursor.fetchone()
                    conn.commit()
                    return row[0] if row else token
                except ResourceNotFoundError:
                    raise
                except Error as exc:
                    rollback_connection(conn)
                    if getattr(exc, "pgcode", None) == UNIQUE_VIOLATION_PGCODE:
                        collision_detected = True
                        break
                    if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                        time.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    raise
                except BaseException:
                    rollback_connection(conn)
                    raise
                finally:
                    cursor.close()

        if collision_detected:
            continue

    raise RuntimeError("Failed to create shared memo token after collision retries.")


def get_shared_memo_payload(token: str) -> dict[str, Any]:
    # 共有トークンに対応する公開メモ内容を返す
    # Return publicly viewable memo payload for the given share token.
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT
                    me.id,
                    me.title,
                    me.tags,
                    me.created_at,
                    me.input_content,
                    me.ai_response
                FROM shared_memo_entries sme
                JOIN memo_entries me ON me.id = sme.memo_entry_id
                WHERE sme.share_token = %s
                LIMIT 1
                """,
                (token,),
            )
            row = cursor.fetchone()
            if not row:
                raise ResourceNotFoundError(ERROR_SHARED_LINK_NOT_FOUND)

            created_at = row.get("created_at")
            return {
                "memo": {
                    "id": row.get("id"),
                    "title": row.get("title") or "保存したメモ",
                    "tags": row.get("tags") or "",
                    "created_at": serialize_datetime_iso(created_at),
                    "input_content": row.get("input_content") or "",
                    "ai_response": row.get("ai_response") or "",
                }
            }
        finally:
            cursor.close()
