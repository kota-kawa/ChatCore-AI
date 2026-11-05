"""メモの共有リンク（共有トークン）の作成・状態取得・取り消しと、公開ページ用のメモ内容の取得。

トークンには有効期限があり（既定30日）、取り消しや期限切れの状態を共通の形式に直して返す。DB 操作は `MemoShareRepository` に委ねる。
Creates, inspects and revokes memo share links (share tokens) and fetches the memo content for the public page.
Tokens expire (30 days by default), and revoked or expired states are returned in a common shape.
Database work is delegated to `MemoShareRepository`.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .datetime_serialization import serialize_datetime_iso
from .db import session_scope
from .repositories.memo_share_repository import MemoShareRepository
from .share_common import (
    SHARED_TOKEN_MAX_COLLISION_RETRIES,
    SHARED_TOKEN_RETRY_BACKOFF_SECONDS,
    TokenShareLifecycle,
    generate_share_token,
    is_unique_violation,
    serialize_token_share_lifecycle,
)

DEFAULT_SHARE_EXPIRES_DAYS = 30
T = TypeVar("T")


def _is_expired(expires_at: Any) -> bool:
    # 有効期限を過ぎているかを、共有トークン共通の判定（TokenShareLifecycle）で調べる。
    # Check expiry with the shared token lifecycle rule (TokenShareLifecycle).
    return TokenShareLifecycle(None, expires_at, None).is_expired


# 共有の状態(トークン・期限・取り消し)を、画面や API へ返す共通の辞書にする。
# Turn the share state (token, expiry, revocation) into the common dict returned to the UI and API.
def _serialize_share_state(
    share_token: str | None,
    expires_at: datetime | None,
    revoked_at: datetime | None,
    *,
    is_reused: bool = False,
) -> dict[str, Any]:
    return serialize_token_share_lifecycle(
        share_token,
        expires_at,
        revoked_at,
        is_reused=is_reused,
    )


def _resolve_expires_at(expires_in_days: int | None) -> datetime | None:
    # 日数から期限(UTC)を求める。None は無期限、1日未満は1日に切り上げる。
    # Convert days to an expiry (UTC): None means no expiry, and anything below 1 day is raised to 1.
    if expires_in_days is None:
        return None
    return datetime.utcnow() + timedelta(days=max(int(expires_in_days), 1))


# 呼び出し側のセッションがあればその中で、無ければ自前のトランザクションを開いて処理を実行する。
# Run the operation inside the caller's session when given, otherwise inside a transaction opened here.
async def _in_transaction(
    session: AsyncSession | None,
    operation: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    if session is not None:
        return await operation(session)
    async with session_scope() as owned_session, owned_session.begin():
        return await operation(owned_session)


def _is_unique_violation(exc: BaseException) -> bool:
    return is_unique_violation(exc)


# 共有トークンを1回だけ作成(または既存を再利用)し、状態の辞書で返す。
# Create (or reuse) a share token exactly once and return the state dict.
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
    # 共有トークンを作成する。既存の有効なトークンがあれば再利用し、force_refresh なら作り直す。
    # 呼び出し側のセッションがある場合は1回だけ試す。無い場合は、トークンの一意制約の衝突時に待ってから再試行する。
    # Create a share token, reusing an existing active one unless force_refresh asks for a new one.
    # With a caller-provided session it tries once; otherwise it retries with backoff on a unique-constraint collision.
    expires_at = _resolve_expires_at(expires_in_days)
    if session is not None:
        return await _create_once(
            session,
            memo_id,
            user_id,
            generate_share_token(secrets.token_urlsafe),
            expires_at,
            force_refresh=force_refresh,
        )

    for attempt in range(SHARED_TOKEN_MAX_COLLISION_RETRIES):
        token = generate_share_token(secrets.token_urlsafe)
        try:
            async with session_scope() as owned_session, owned_session.begin():
                return await _create_once(
                    owned_session,
                    memo_id,
                    user_id,
                    token,
                    expires_at,
                    force_refresh=force_refresh,
                )
        except IntegrityError as exc:
            if not _is_unique_violation(exc) or attempt + 1 >= SHARED_TOKEN_MAX_COLLISION_RETRIES:
                raise
            await asyncio.sleep(SHARED_TOKEN_RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise RuntimeError("Failed to create shared memo token after collision retries.")


# メモの共有状態を取得する。共有していなければ「共有なし」の状態を返す。
# Get a memo's share state; returns the "not shared" state when it has no share.
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


# メモの共有トークンを取り消し、取り消し後の状態を返す。
# Revoke a memo's share token and return the resulting state.
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


# 共有トークンから、公開ページに表示するメモの内容（タイトル、作成日時、本文、背景色）を組み立てる。
# Build the memo content shown on the public page (title, created time, body, background color) from a share token.
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
