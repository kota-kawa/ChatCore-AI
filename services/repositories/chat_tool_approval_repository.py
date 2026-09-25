"""Async SQLAlchemy persistence boundary for chat write-tool approvals and their grants.

This repository owns the chat_tool_approvals rows (one per approval card) and the
chat_tool_auto_approvals rows ("always approve" grants).  Every lookup is scoped
to the owning user, so another user's approval id resolves to nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import ChatToolApproval, ChatToolAutoApproval


class ChatToolApprovalRepository:
    """Repository for approval cards and "always approve" grants.

    The repository never commits.  Services own the transaction and pass an
    isolated AsyncSession for one unit of work.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Approvals --------------------------------------------------------------

    async def insert_approval(
        self,
        *,
        approval_id: UUID,
        user_id: int,
        chat_room_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        preview: dict[str, Any],
        target_ref: dict[str, Any] | None,
        status: str,
        expires_at: datetime,
        decision: str | None = None,
        result: dict[str, Any] | None = None,
        decided_at: datetime | None = None,
    ) -> ChatToolApproval:
        row = ChatToolApproval(
            id=approval_id,
            user_id=user_id,
            chat_room_id=chat_room_id,
            tool_name=tool_name,
            arguments=arguments,
            preview=preview,
            target_ref=target_ref,
            status=status,
            decision=decision,
            result=result,
            expires_at=expires_at,
            decided_at=decided_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    # 利用者が操作できる行だけを返す。回答に結び付いていない行（生成中・保存失敗）は
    # カードとして表示されていないので、見つからない扱いにする。
    # Return only rows the user can act on. A row not yet tied to a saved reply (still
    # generating, or the save failed) was never shown as a card, so it reads as missing.
    async def get_actionable(
        self,
        approval_id: UUID,
        user_id: int,
        *,
        for_update: bool = False,
    ) -> ChatToolApproval | None:
        statement = select(ChatToolApproval).where(
            ChatToolApproval.id == approval_id,
            ChatToolApproval.user_id == user_id,
            ChatToolApproval.assistant_message_id.is_not(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def settle(
        self,
        row: ChatToolApproval,
        *,
        status: str,
        decision: str | None,
        result: dict[str, Any] | None,
        decided_at: datetime,
    ) -> ChatToolApproval:
        row.status = status
        row.decision = decision
        row.result = result
        row.decided_at = decided_at
        await self.session.flush()
        return row

    # 保存した回答へ承認行を結び付ける。生成中に作った行だけが対象。
    # Tie approval rows to the saved reply; only rows created during generation qualify.
    async def attach_message(
        self,
        approval_ids: Sequence[UUID],
        *,
        user_id: int,
        chat_room_id: str,
        message_id: int,
    ) -> int:
        if not approval_ids:
            return 0
        result = await self.session.execute(
            update(ChatToolApproval)
            .where(
                ChatToolApproval.id.in_(list(approval_ids)),
                ChatToolApproval.user_id == user_id,
                ChatToolApproval.chat_room_id == chat_room_id,
                ChatToolApproval.assistant_message_id.is_(None),
            )
            .values(assistant_message_id=message_id)
        )
        return int(result.rowcount or 0)

    # ルームの承認待ちのうち、保存済みの回答にあるものを別の状態へ移し、移した行を返す
    # （パーツの書き換えに使う）。回答へ結び付く前の行は実行中の生成の持ち物なので触らない。
    # Move a room's pending approvals that sit on a saved reply to another status and return them
    # for the part updates. Rows not yet tied to a reply belong to a running generation.
    async def settle_pending_in_room(
        self,
        chat_room_id: str,
        *,
        user_id: int,
        status: str,
        decided_at: datetime,
    ) -> list[ChatToolApproval]:
        rows = (
            await self.session.execute(
                select(ChatToolApproval)
                .where(
                    ChatToolApproval.chat_room_id == chat_room_id,
                    ChatToolApproval.user_id == user_id,
                    ChatToolApproval.status == "pending",
                    ChatToolApproval.assistant_message_id.is_not(None),
                )
                .order_by(ChatToolApproval.created_at, ChatToolApproval.id)
                .with_for_update()
            )
        ).scalars().all()
        for row in rows:
            row.status = status
            row.decided_at = decided_at
        await self.session.flush()
        return list(rows)

    # 回答へ結び付かないまま一定時間が過ぎた行を消す。カードとして表示されることはない。
    # Delete rows never tied to a reply after a grace period; they can never show as a card.
    async def delete_orphans_in_room(
        self,
        chat_room_id: str,
        *,
        user_id: int,
        created_before: datetime,
    ) -> int:
        result = await self.session.execute(
            delete(ChatToolApproval).where(
                ChatToolApproval.chat_room_id == chat_room_id,
                ChatToolApproval.user_id == user_id,
                ChatToolApproval.assistant_message_id.is_(None),
                ChatToolApproval.created_at < created_before,
            )
        )
        return int(result.rowcount or 0)

    # 停止した生成が残した承認待ちを取り消す。回答へ結び付く前の行だけが対象。
    # Cancel the pending rows a stopped generation left behind, before they reach a reply.
    async def cancel_unattached(
        self,
        approval_ids: Sequence[UUID],
        *,
        user_id: int,
        decided_at: datetime,
    ) -> int:
        if not approval_ids:
            return 0
        result = await self.session.execute(
            update(ChatToolApproval)
            .where(
                ChatToolApproval.id.in_(list(approval_ids)),
                ChatToolApproval.user_id == user_id,
                ChatToolApproval.status == "pending",
                ChatToolApproval.assistant_message_id.is_(None),
            )
            .values(status="cancelled", decided_at=decided_at)
        )
        return int(result.rowcount or 0)

    # "Always approve" grants -----------------------------------------------

    async def has_grant(self, user_id: int, tool_name: str) -> bool:
        grant_id = await self.session.scalar(
            select(ChatToolAutoApproval.id).where(
                ChatToolAutoApproval.user_id == user_id,
                ChatToolAutoApproval.tool_name == tool_name,
            )
        )
        return grant_id is not None

    async def list_grants(self, user_id: int) -> list[ChatToolAutoApproval]:
        return list(
            (
                await self.session.execute(
                    select(ChatToolAutoApproval)
                    .where(ChatToolAutoApproval.user_id == user_id)
                    .order_by(ChatToolAutoApproval.created_at, ChatToolAutoApproval.id)
                )
            ).scalars().all()
        )

    # 付与は冪等。既にあれば元の付与日時と付与元を残す。
    # Granting is idempotent; an existing grant keeps its original time and source.
    async def upsert_grant(self, user_id: int, tool_name: str, source_approval_id: UUID) -> None:
        await self.session.execute(
            pg_insert(ChatToolAutoApproval)
            .values(user_id=user_id, tool_name=tool_name, source_approval_id=source_approval_id)
            .on_conflict_do_nothing(constraint="uq_chat_tool_auto_approvals_user_tool")
        )

    async def delete_grant(self, user_id: int, tool_name: str) -> bool:
        result = await self.session.execute(
            delete(ChatToolAutoApproval).where(
                ChatToolAutoApproval.user_id == user_id,
                ChatToolAutoApproval.tool_name == tool_name,
            )
        )
        return bool(result.rowcount)
