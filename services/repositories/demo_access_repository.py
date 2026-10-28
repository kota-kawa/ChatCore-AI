"""SQLAlchemy persistence for demo access codes."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import DemoAccessCode


class DemoAccessRepository:
    """Read and lock demo access code rows; the service owns the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert(self, *, label: str, code_digest: str) -> DemoAccessCode:
        row = DemoAccessCode(label=label, code_digest=code_digest)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def list_all(self) -> list[DemoAccessCode]:
        result = await self.session.scalars(
            select(DemoAccessCode).order_by(DemoAccessCode.created_at.desc(), DemoAccessCode.id.desc())
        )
        return list(result)

    async def lock_by_digest(self, code_digest: str) -> DemoAccessCode | None:
        # 同じコードの初回利用が同時に来ても、デモ用ユーザーを1人しか作らないよう行をロックする。
        # Lock the row so two simultaneous first uses of one code create only one demo user.
        return await self.session.scalar(
            select(DemoAccessCode).where(DemoAccessCode.code_digest == code_digest).with_for_update()
        )

    async def lock_by_id(self, code_id: int) -> DemoAccessCode | None:
        return await self.session.scalar(
            select(DemoAccessCode).where(DemoAccessCode.id == int(code_id)).with_for_update()
        )

    async def lock_expired(self, now: datetime, *, limit: int) -> list[DemoAccessCode]:
        # 別のワーカーが同じ行を削除中なら飛ばし、次の周期に任せる。
        # Skip rows another worker is already purging; the next cycle picks up anything left.
        result = await self.session.scalars(
            select(DemoAccessCode)
            .where(DemoAccessCode.user_id.is_not(None), DemoAccessCode.expires_at <= now)
            .order_by(DemoAccessCode.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result)

    async def expiry_for_user(self, user_id: int) -> datetime | None:
        return await self.session.scalar(
            select(DemoAccessCode.expires_at).where(DemoAccessCode.user_id == int(user_id))
        )
