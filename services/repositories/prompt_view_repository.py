"""Persistence boundary for public prompt view counters."""

from __future__ import annotations

from services.db import get_db_connection


class PromptViewRepository:
    """Record prompt views without mutating prompts or their revision history."""

    @staticmethod
    def increment_public_view(prompt_id: int) -> int | None:
        """Atomically increment an active public prompt and return its new count."""
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    INSERT INTO prompt_view_counts AS pvc (prompt_id, view_count)
                    SELECT p.id, 1
                    FROM prompts AS p
                    WHERE p.id = %s
                      AND p.is_public = TRUE
                      AND p.deleted_at IS NULL
                    ON CONFLICT (prompt_id) DO UPDATE
                    SET view_count = pvc.view_count + 1
                    RETURNING view_count
                    """,
                    (int(prompt_id),),
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    return None
                conn.commit()
                return int(row.get("view_count") or 0)
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()
