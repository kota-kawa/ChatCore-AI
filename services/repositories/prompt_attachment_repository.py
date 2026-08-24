"""Persistence for prompt attachment references."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import Prompt


class PromptAttachmentRepository:
    """Read attachment metadata used by the file reconciliation job."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active_attachments(self) -> list[dict[str, Any]]:
        values = await self.session.scalars(
            select(Prompt.attachments).where(
                Prompt.deleted_at.is_(None),
                Prompt.attachments.is_not(None),
            )
        )
        attachments: list[dict[str, Any]] = []
        for value in values:
            if isinstance(value, list):
                attachments.extend(item for item in value if isinstance(item, dict))
        return attachments
