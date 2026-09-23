"""SQLAlchemy persistence for daily API usage totals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import ApiUsageDaily


@dataclass(frozen=True, slots=True)
class UsageIncrement:
    """One metered API call (or a batch of them) to add to a day's totals."""

    subject_key: str
    usage_date: date
    resource: str
    cost_nano_usd: int
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 1


class UsageRepository:
    """Accumulate usage per (subject, day, resource) with an atomic upsert."""

    async def add_usage(self, session: AsyncSession, increment: UsageIncrement) -> None:
        values = {
            "subject_key": increment.subject_key,
            "usage_date": increment.usage_date,
            "resource": increment.resource,
            "cost_nano_usd": increment.cost_nano_usd,
            "input_tokens": increment.input_tokens,
            "cached_input_tokens": increment.cached_input_tokens,
            "output_tokens": increment.output_tokens,
            "request_count": increment.request_count,
        }
        statement = pg_insert(ApiUsageDaily).values(**values)
        # 同じ行へ同時に書いても取りこぼさないよう、読み出してから足すのではなく
        # 行ロック付きの UPSERT で加算する。
        # Add inside the upsert rather than read-modify-write so concurrent writers to the
        # same row never lose an increment.
        statement = statement.on_conflict_do_update(
            index_elements=[
                ApiUsageDaily.subject_key,
                ApiUsageDaily.usage_date,
                ApiUsageDaily.resource,
            ],
            set_={
                "cost_nano_usd": ApiUsageDaily.cost_nano_usd + statement.excluded.cost_nano_usd,
                "input_tokens": ApiUsageDaily.input_tokens + statement.excluded.input_tokens,
                "cached_input_tokens": ApiUsageDaily.cached_input_tokens
                + statement.excluded.cached_input_tokens,
                "output_tokens": ApiUsageDaily.output_tokens + statement.excluded.output_tokens,
                "request_count": ApiUsageDaily.request_count + statement.excluded.request_count,
                "updated_at": func.now(),
            },
        )
        await session.execute(statement)
