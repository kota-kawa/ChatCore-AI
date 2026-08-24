from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
import secrets
from typing import Any, TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .datetime_serialization import serialize_datetime_iso
from .db import session_scope
from .repositories.memo_share_repository import MemoShareRepository

UNIQUE_VIOLATION_PGCODE = "23505"
SHARED_TOKEN_MAX_COLLISION_RETRIES = 5
DEFAULT_SHARE_EXPIRES_DAYS = 30
T = TypeVar("T")


def _is_expired(expires_at: Any) -> bool:
    return isinstance(expires_at, datetime) and expires_at <= datetime.utcnow()


def _serialize_share_state(
    share_token: str | None,
    expires_at: datetime | None,
    revoked_at: datetime | None,
    *,
    is_reused: bool = False,
) -> dict[str, Any]:
    expired = _is_expired(expires_at)
    return {
        "share_token": share_token or "",
        "expires_at": serialize_datetime_iso(expires_at),
        "revoked_at": serialize_datetime_iso(revoked_at),
        "is_expired": expired,
        "is_revoked": revoked_at is not None,
        "is_active": bool(share_token) and revoked_at is None and not expired,
        "is_reused": is_reused,
    }


def _resolve_expires_at(expires_in_days: int | None) -> datetime | None:
    if expires_in_days is None:
        return None
    return datetime.utcnow() + timedelta(days=max(int(expires_in_days), 1))


async def _in_transaction(
    session: AsyncSession | None,
    operation: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    if session is not None:
        return await operation(session)
    async with session_scope() as owned_session:
        async with owned_session.begin():
            return await operation(owned_session)


def _sqlstate(exc: BaseException) -> str | None:
    current: BaseException | None = exc
    for _ in range(3):
        if current is None:
            return None
        value = getattr(current, "sqlstate", None)
        if value:
            return str(value)
        current = getattr(current, "orig", None)
        if not isinstance(current, BaseException):
            return None
    return None


async def _create_once(
    session: AsyncSession,
    memo_id: int,
    user_id: int,
    token: str,
    expires_at: datetime | None,
    *,
    force_refresh: bool,
) -> dict[str, Any]:
    row = await MemoShareRepository(session).create_or_get(
        memo_id,
        user_id,
        token,
        expires_at,
        force_refresh=force_refresh,
    )
    return _serialize_share_state(
        row.get("share_token"),
        row.get("expires_at"),
        row.get("revoked_at"),
        is_reused=bool(row.get("is_reused")),
    )


async def create_or_get_shared_memo_token(
    memo_id: int,
    user_id: int,
    *,
    force_refresh: bool = False,
    expires_in_days: int | None = DEFAULT_SHARE_EXPIRES_DAYS,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    expires_at = _resolve_expires_at(expires_in_days)
    if session is not None:
        return await _create_once(
            session,
            memo_id,
            user_id,
            secrets.token_urlsafe(18),
            expires_at,
            force_refresh=force_refresh,
        )

    for attempt in range(SHARED_TOKEN_MAX_COLLISION_RETRIES):
        token = secrets.token_urlsafe(18)
        try:
            async with session_scope() as owned_session:
                async with owned_session.begin():
                    return await _create_once(
                        owned_session,
                        memo_id,
                        user_id,
                        token,
                        expires_at,
                        force_refresh=force_refresh,
                    )
        except IntegrityError as exc:
            if _sqlstate(exc) != UNIQUE_VIOLATION_PGCODE or attempt + 1 >= SHARED_TOKEN_MAX_COLLISION_RETRIES:
                raise
            await asyncio.sleep(0.05 * (attempt + 1))
    raise RuntimeError("Failed to create shared memo token after collision retries.")


async def get_memo_share_state(
    memo_id: int,
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    async def operation(db: AsyncSession) -> dict[str, Any]:
        row = await MemoShareRepository(db).get_state(memo_id, user_id)
        if row is None:
            return _serialize_share_state(None, None, None)
        return _serialize_share_state(row["share_token"], row["expires_at"], row["revoked_at"])

    return await _in_transaction(session, operation)


async def revoke_shared_memo_token(
    memo_id: int,
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    async def operation(db: AsyncSession) -> dict[str, Any]:
        row = await MemoShareRepository(db).revoke(memo_id, user_id)
        if row is None:
            return _serialize_share_state(None, None, None)
        return _serialize_share_state(row["share_token"], row["expires_at"], row["revoked_at"])

    return await _in_transaction(session, operation)


async def get_shared_memo_payload(
    token: str,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    async def operation(db: AsyncSession) -> dict[str, Any]:
        row = await MemoShareRepository(db).get_public_payload(token)
        return {
            "memo": {
                "id": row["id"],
                "title": row["title"] or "保存したメモ",
                "created_at": serialize_datetime_iso(row["created_at"]),
                "ai_response": row["ai_response"] or "",
                "background_color": row["background_color"],
            }
        }

    return await _in_transaction(session, operation)
