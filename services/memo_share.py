from __future__ import annotations

import secrets
from typing import Any

from .db import get_db_connection

UNIQUE_VIOLATION_PGCODE = "23505"


def create_or_get_shared_memo_token(memo_id: int, user_id: int) -> tuple[str | None, int | None]:
    # メモ所有者を検証した上で共有トークンを作成し、既存があれば再利用する
    # Create a memo share token after owner validation and reuse the existing one.
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM memo_entries WHERE id = %s AND user_id = %s",
            (memo_id, user_id),
        )
        if not cursor.fetchone():
            return None, 404

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
                return (row[0] if row else token), None
            except Exception as exc:
                conn.rollback()
                if getattr(exc, "pgcode", None) == UNIQUE_VIOLATION_PGCODE:
                    continue
                raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def get_shared_memo_payload(token: str) -> tuple[dict[str, Any], int]:
    # 共有トークンに対応する公開メモ内容を返す
    # Return publicly viewable memo payload for the given share token.
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
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
            return {"error": "共有リンクが見つかりません"}, 404

        created_at = row.get("created_at")
        return (
            {
                "memo": {
                    "id": row.get("id"),
                    "title": row.get("title") or "保存したメモ",
                    "tags": row.get("tags") or "",
                    "created_at": created_at.strftime("%Y-%m-%d %H:%M") if created_at else None,
                    "input_content": row.get("input_content") or "",
                    "ai_response": row.get("ai_response") or "",
                }
            },
            200,
        )
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
