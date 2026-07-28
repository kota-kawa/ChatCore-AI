from __future__ import annotations

from typing import Any

from services.db import get_db_connection
from services.i18n import Locale, normalize_locale


def get_user_preferred_locale(user_id: int) -> Locale | None:
    """Return the user's explicitly saved locale, or None when unset/missing."""
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT preferred_locale FROM users WHERE id = %s",
                (int(user_id),),
            )
            row: dict[str, Any] | None = cursor.fetchone()
            if not row:
                return None
            return normalize_locale(row.get("preferred_locale"))
        finally:
            cursor.close()


def update_user_preferred_locale(user_id: int, locale: Locale) -> bool:
    """Persist a locale and report whether the user row existed."""
    normalized = normalize_locale(locale)
    if normalized is None:
        raise ValueError("Unsupported locale")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE users
                   SET preferred_locale = %s
                 WHERE id = %s
                RETURNING id
                """,
                (normalized, int(user_id)),
            )
            updated = cursor.fetchone() is not None
            if updated:
                conn.commit()
            else:
                conn.rollback()
            return updated
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
