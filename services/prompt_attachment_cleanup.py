"""Reconcile local prompt-share attachment files with active prompt records."""

from __future__ import annotations

import logging
from typing import Any

from services.db import get_db_connection
from services.prompt_attachment_storage import cleanup_unreferenced_prompt_attachments


logger = logging.getLogger(__name__)


def cleanup_orphaned_prompt_attachments() -> int:
    """Delete old local variants not referenced by an active prompt.

    The local backend is intentionally reconciled from database truth. This
    makes failed writes and files left by a process crash recoverable, while a
    future object-store backend can retain the same reconciliation contract.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT attachments
                  FROM prompts
                 WHERE deleted_at IS NULL
                   AND attachments IS NOT NULL
                """
            )
            attachments: list[dict[str, Any]] = []
            for row in cursor.fetchall():
                values = row.get("attachments")
                if isinstance(values, list):
                    attachments.extend(value for value in values if isinstance(value, dict))
        finally:
            cursor.close()

    deleted = cleanup_unreferenced_prompt_attachments(attachments)
    if deleted:
        logger.info("Removed %s unreferenced prompt attachment files.", deleted)
    return deleted
