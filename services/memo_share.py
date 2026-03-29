from __future__ import annotations

import secrets
from typing import Any

from .api_errors import ResourceNotFoundError
from .db import get_db_connection
from .error_messages import ERROR_MEMO_NOT_FOUND_FOR_SHARE, ERROR_SHARED_LINK_NOT_FOUND

UNIQUE_VIOLATION_PGCODE = "23505"


def create_or_get_shared_memo_token(memo_id: int, user_id: int) -> str:
    # メモ所有者を検証した上で共有トークンを作成し、既存があれば再利用する
    # Create a memo share token after owner validation and reuse the existing one.
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM memo_entries WHERE id = %s AND user_id = %s",
                (memo_id, user_id),
            )
            if not cursor.fetchone():
                raise ResourceNotFoundError(ERROR_MEMO_NOT_FOUND_FOR_SHARE)

            while True:
                token = secrets.token_urlsafe(18)
                try:
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
                except Exception as exc:
                    conn.rollback()
                    if getattr(exc, "pgcode", None) == UNIQUE_VIOLATION_PGCODE:
                        continue
                    raise
        finally:
            cursor.close()


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
                    "created_at": created_at.strftime("%Y-%m-%d %H:%M") if created_at else None,
                    "input_content": row.get("input_content") or "",
                    "ai_response": row.get("ai_response") or "",
                }
            }
        finally:
            cursor.close()
