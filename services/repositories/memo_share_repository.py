"""Persistence operations for memo share links."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ResourceNotFoundError
from services.error_messages import ERROR_MEMO_NOT_FOUND_FOR_SHARE, ERROR_SHARED_LINK_NOT_FOUND
from services.models import MemoEntry, SharedMemoEntry


class MemoShareRepository:
    """Read and write share-link rows without owning the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _is_active(row: Any) -> bool:
        expires_at = row.get("expires_at") if hasattr(row, "get") else None
        revoked_at = row.get("revoked_at") if hasattr(row, "get") else None
        return revoked_at is None and (
            expires_at is None or expires_at > datetime.utcnow()
        )

    async def create_or_get(
        self,
        memo_id: int,
        user_id: int,
        token: str,
        expires_at: datetime | None,
        *,
        force_refresh: bool,
    ) -> dict[str, Any]:
        owner = await self.session.scalar(
            select(MemoEntry.id).where(
                MemoEntry.id == memo_id,
                MemoEntry.user_id == user_id,
            )
        )
        if owner is None:
            raise ResourceNotFoundError(ERROR_MEMO_NOT_FOUND_FOR_SHARE)

        if not force_refresh:
            existing = await self.session.execute(
                select(
                    SharedMemoEntry.share_token,
                    SharedMemoEntry.expires_at,
                    SharedMemoEntry.revoked_at,
                ).where(SharedMemoEntry.memo_entry_id == memo_id)
            )
            row = existing.mappings().first()
            if row is not None and self._is_active(row):
                return {**dict(row), "is_reused": True}

        statement = (
            pg_insert(SharedMemoEntry)
            .values(
                memo_entry_id=memo_id,
                share_token=token,
                expires_at=expires_at,
                revoked_at=None,
            )
            .on_conflict_do_update(
                index_elements=[SharedMemoEntry.memo_entry_id],
                set_={
                    "share_token": token,
                    "expires_at": expires_at,
                    "revoked_at": None,
                    "created_at": func.current_timestamp(),
                },
            )
            .returning(
                SharedMemoEntry.share_token,
                SharedMemoEntry.expires_at,
                SharedMemoEntry.revoked_at,
            )
        )
        result = await self.session.execute(statement)
        row = result.mappings().first()
        if row is None:  # pragma: no cover - PostgreSQL RETURNING invariant
            return {
                "share_token": token,
                "expires_at": expires_at,
                "revoked_at": None,
                "is_reused": False,
            }
        return {**dict(row), "is_reused": False}

    async def get_state(self, memo_id: int, user_id: int) -> dict[str, Any] | None:
        owner = await self.session.scalar(
            select(MemoEntry.id).where(
                MemoEntry.id == memo_id,
                MemoEntry.user_id == user_id,
            )
        )
        if owner is None:
            raise ResourceNotFoundError(ERROR_MEMO_NOT_FOUND_FOR_SHARE)
        result = await self.session.execute(
            select(
                SharedMemoEntry.share_token,
                SharedMemoEntry.expires_at,
                SharedMemoEntry.revoked_at,
            ).where(SharedMemoEntry.memo_entry_id == memo_id)
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def revoke(self, memo_id: int, user_id: int) -> dict[str, Any] | None:
        owner = await self.session.scalar(
            select(MemoEntry.id).where(
                MemoEntry.id == memo_id,
                MemoEntry.user_id == user_id,
            )
        )
        if owner is None:
            raise ResourceNotFoundError(ERROR_MEMO_NOT_FOUND_FOR_SHARE)
        result = await self.session.execute(
            update(SharedMemoEntry)
            .where(SharedMemoEntry.memo_entry_id == memo_id)
            .values(revoked_at=func.current_timestamp())
            .returning(
                SharedMemoEntry.share_token,
                SharedMemoEntry.expires_at,
                SharedMemoEntry.revoked_at,
            )
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def get_public_payload(self, token: str) -> dict[str, Any]:
        result = await self.session.execute(
            select(
                MemoEntry.id,
                MemoEntry.title,
                MemoEntry.created_at,
                MemoEntry.ai_response,
                MemoEntry.background_color,
            )
            .select_from(SharedMemoEntry)
            .join(MemoEntry, MemoEntry.id == SharedMemoEntry.memo_entry_id)
            .where(
                SharedMemoEntry.share_token == token,
                SharedMemoEntry.revoked_at.is_(None),
                (
                    SharedMemoEntry.expires_at.is_(None)
                    | (SharedMemoEntry.expires_at > func.current_timestamp())
                ),
            )
        )
        row = result.mappings().first()
        if row is None:
            raise ResourceNotFoundError(ERROR_SHARED_LINK_NOT_FOUND)
        return dict(row)
