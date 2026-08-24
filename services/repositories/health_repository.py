"""Database readiness probes executed through SQLAlchemy Core."""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import User


class HealthRepository:
    """Run the minimal queries needed to validate the application schema."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def check_database(self) -> None:
        await self.session.scalar(select(func.count()).select_from(User))
        await self.session.scalar(text("SELECT 1"))
