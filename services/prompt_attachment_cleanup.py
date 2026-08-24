"""Reconcile local prompt-share attachment files with active prompt records."""

from __future__ import annotations

import asyncio
import logging

from services.db import session_scope
from services.prompt_attachment_storage import cleanup_unreferenced_prompt_attachments
from services.repositories.prompt_attachment_repository import PromptAttachmentRepository


logger = logging.getLogger(__name__)


async def cleanup_orphaned_prompt_attachments() -> int:
    """Delete old local variants not referenced by an active prompt.

    The local backend is intentionally reconciled from database truth. This
    makes failed writes and files left by a process crash recoverable, while a
    future object-store backend can retain the same reconciliation contract.
    """
    async with session_scope() as session:
        attachments = await PromptAttachmentRepository(session).list_active_attachments()

    # File reconciliation is blocking I/O, but it is deliberately outside the
    # database session and does not use the DB blocking executor.
    deleted = await asyncio.to_thread(
        cleanup_unreferenced_prompt_attachments, attachments
    )
    if deleted:
        logger.info("Removed %s unreferenced prompt attachment files.", deleted)
    return deleted
