"""PostgreSQL integration coverage for deciding chat approval cards.

単体テスト（tests/unit/test_chat_tool_approval_api.py）はリポジトリを代役にするため、セッションを
閉じた後に ORM の行を読むと失効して DetachedInstanceError になる、という実 DB でしか起きない
失敗を検出できない。ここでは実際の session_scope とリポジトリで承認・拒否・一覧を通す。
The unit tests replace the repository with doubles, so they cannot catch a failure that only a
real session shows: reading an ORM row after its session closed raises DetachedInstanceError once
the closing rollback expired it. This runs approve, deny and the grant list through the real
session_scope and repositories.
"""

from __future__ import annotations

import os
import unittest
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from services.auth_limits import AuthLimitService
from services.chat_tool_approval_service import (
    create_pending_approval,
    decide_tool_approval,
    list_auto_approvals,
    save_assistant_message_with_approvals,
)
from services.chat_workspace_tools.registry import Proposal
from services.db import dispose_engine, session_scope
from services.tool_approval_parts import tool_approval_part


@unittest.skipUnless(
    os.environ.get("DATABASE_URL"),
    "requires DATABASE_URL pointing at a PostgreSQL test database",
)
class ChatToolApprovalDecisionIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        suffix = uuid4().hex
        self.room_id = f"integration-approval-{suffix}"
        async with session_scope() as session, session.begin():
            self.user_id = int(
                (
                    await session.execute(
                        text("INSERT INTO users (email, username) VALUES (:email, :username) RETURNING id"),
                        {"email": f"tool-approval-{suffix}@example.test", "username": "承認テスト"},
                    )
                ).scalar_one()
            )
            await session.execute(
                text("INSERT INTO chat_rooms (id, user_id, title, mode) VALUES (:room_id, :user_id, 'approval', 'normal')"),
                {"room_id": self.room_id, "user_id": self.user_id},
            )
        self.auth_limit_service = AuthLimitService(redis_client_getter=lambda: None)

    async def asyncTearDown(self) -> None:
        async with session_scope() as session, session.begin():
            # memo_entries は users の削除で連鎖しないので先に消す
            # memo_entries do not cascade from users, so they go first
            await session.execute(text("DELETE FROM memo_entries WHERE user_id = :user_id"), {"user_id": self.user_id})
            await session.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": self.user_id})
        await dispose_engine()

    async def _propose_memo(self, content: str) -> dict[str, Any]:
        proposal = Proposal(
            arguments={"title": "承認テスト", "content": content},
            preview={"kind": "memo_create", "title": "承認テスト", "content": content},
            target_ref={},
            target_title="承認テスト",
        )
        card = await create_pending_approval(
            user_id=self.user_id,
            chat_room_id=self.room_id,
            tool_name="memo_create",
            proposal=proposal,
            untrusted_input=False,
        )
        message_id = await save_assistant_message_with_approvals(
            chat_room_id=self.room_id,
            user_id=self.user_id,
            message="承認してください。",
            parent_id=None,
            message_parts=[tool_approval_part(card)],
            web_search_context=None,
            approval_ids=[card["id"]],
        )
        self.assertIsNotNone(message_id)
        return card

    async def _decide(self, card: dict[str, Any], decision: str) -> dict[str, Any]:
        return await decide_tool_approval(
            self.user_id,
            UUID(card["id"]),
            decision,
            auth_limit_service=self.auth_limit_service,
        )

    async def _memo_count(self) -> int:
        async with session_scope() as session:
            return int(
                (
                    await session.execute(
                        text("SELECT COUNT(*) FROM memo_entries WHERE user_id = :user_id"),
                        {"user_id": self.user_id},
                    )
                ).scalar_one()
            )

    async def test_deny_settles_the_card_without_writing(self) -> None:
        card = await self._propose_memo("拒否する本文")

        decided = await self._decide(card, "deny")

        self.assertEqual(decided["status"], "denied")
        self.assertEqual(decided["decision"], "deny")
        self.assertEqual(await self._memo_count(), 0)
        # 決定済みへの同じ決定の再送は冪等に同じカードを返す
        # Repeating the same decision on a settled card returns it idempotently
        self.assertEqual((await self._decide(card, "deny"))["status"], "denied")

    async def test_approve_once_runs_the_tool(self) -> None:
        card = await self._propose_memo("承認する本文")

        decided = await self._decide(card, "approve_once")

        self.assertEqual(decided["status"], "succeeded")
        self.assertEqual(decided["decision"], "once")
        self.assertEqual(await self._memo_count(), 1)

    async def test_approve_always_grant_is_listed(self) -> None:
        card = await self._propose_memo("常に承認する本文")

        decided = await self._decide(card, "approve_always")
        grants = await list_auto_approvals(self.user_id)

        self.assertEqual(decided["status"], "succeeded")
        self.assertEqual([grant["tool_name"] for grant in grants], ["memo_create"])
        self.assertEqual(grants[0]["family"], "memo")


if __name__ == "__main__":
    unittest.main()
