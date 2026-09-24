"""承認 API（blueprints/chat/tool_approvals.py）とその決定ロジック（services/chat_tool_approval_service.py）
の契約を検証する。

Verifies the contract of the approval API (blueprints/chat/tool_approvals.py) and its decision
logic (services/chat_tool_approval_service.py).

サービス層は実 DB を使わず、リポジトリと ChatRepository をインメモリの代役に差し替えて検証する
（AGENTS.md: 実 DB・.env は使わない）。ツールの実行そのもの（メモの作成・追記・書き換え）は
tests/unit/test_chat_workspace_tools.py が担保するため、ここでは ToolSpec を代役に絞って
決定ロジックの分岐だけを見る。
The service layer is tested without a real database: the repository and ChatRepository are
replaced with in-memory doubles (AGENTS.md: no real DB, no .env). Running an actual tool (memo
create/append/edit) is covered by tests/unit/test_chat_workspace_tools.py; here a fake ToolSpec
stands in so only the decision logic branches are exercised.
"""

from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx

from services.api_errors import ApiServiceError
from services.auth_limits import AuthLimitService, get_auth_limit_service
from services.chat_tool_approval_service import (
    ChatToolRateLimitedError,
    cancel_unattached_approvals,
    create_pending_approval,
    decide_tool_approval,
    execute_auto_approved,
    list_auto_approvals,
    revoke_auto_approval,
    supersede_pending_approvals,
)
from services.chat_workspace_tools.registry import ExecutionOutcome, Proposal, ToolSpec, WorkspaceToolError
from services.csrf import CSRF_HEADER_NAME, CSRF_SESSION_KEY
from tests.helpers.app_helpers import build_session_test_app

# 承認カードは services/response_models.py の ToolApprovalApi を正本に検証されるため、ツール名と
# プレビューの形は PR1 が定義する実在のもの（memo_create）を使う。実行ハンドラだけを代役にする。
# Approval cards validate against ToolApprovalApi (services/response_models.py), so the tool name
# and preview shape use a real one PR1 defines (memo_create); only the execute handler is faked.
TOOL_NAME = "memo_create"


def _preview(content: str = "hi") -> dict[str, Any]:
    return {"kind": TOOL_NAME, "title": "Target", "content": content}


# --- In-memory doubles for the repository boundary ---------------------------------------------


@dataclass
class _Row:
    id: UUID
    user_id: int
    chat_room_id: str
    tool_name: str
    arguments: dict[str, Any]
    preview: dict[str, Any]
    target_ref: dict[str, Any] | None
    status: str
    expires_at: datetime
    assistant_message_id: int | None = None
    decision: str | None = None
    result: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None


class _FakeStore:
    def __init__(self) -> None:
        self.rows: dict[UUID, _Row] = {}
        self.grants: dict[tuple[int, str], Any] = {}


class _FakeApprovalRepository:
    """Mirrors services/repositories/chat_tool_approval_repository.py in memory."""

    def __init__(self, store: _FakeStore) -> None:
        self.store = store

    async def insert_approval(
        self,
        *,
        approval_id,
        user_id,
        chat_room_id,
        tool_name,
        arguments,
        preview,
        target_ref,
        status,
        expires_at,
        decision=None,
        result=None,
        decided_at=None,
    ):
        row = _Row(
            id=approval_id,
            user_id=user_id,
            chat_room_id=chat_room_id,
            tool_name=tool_name,
            arguments=arguments,
            preview=preview,
            target_ref=target_ref,
            status=status,
            expires_at=expires_at,
            decision=decision,
            result=result,
            decided_at=decided_at,
        )
        self.store.rows[approval_id] = row
        return row

    async def get_actionable(self, approval_id, user_id, *, for_update=False):
        row = self.store.rows.get(approval_id)
        if row is None or row.user_id != user_id or row.assistant_message_id is None:
            return None
        return row

    async def settle(self, row, *, status, decision, result, decided_at):
        row.status = status
        row.decision = decision
        row.result = result
        row.decided_at = decided_at
        return row

    async def attach_message(self, approval_ids, *, user_id, chat_room_id, message_id):
        count = 0
        for approval_id in approval_ids:
            row = self.store.rows.get(approval_id)
            if (
                row is not None
                and row.user_id == user_id
                and row.chat_room_id == chat_room_id
                and row.assistant_message_id is None
            ):
                row.assistant_message_id = message_id
                count += 1
        return count

    async def settle_pending_in_room(self, chat_room_id, *, user_id, status, decided_at):
        rows = [
            row
            for row in self.store.rows.values()
            if row.chat_room_id == chat_room_id
            and row.user_id == user_id
            and row.status == "pending"
            and row.assistant_message_id is not None
        ]
        for row in rows:
            row.status = status
            row.decided_at = decided_at
        return rows

    async def delete_orphans_in_room(self, chat_room_id, *, user_id, created_before):
        orphan_ids = [
            approval_id
            for approval_id, row in self.store.rows.items()
            if row.chat_room_id == chat_room_id
            and row.user_id == user_id
            and row.assistant_message_id is None
            and row.created_at < created_before
        ]
        for approval_id in orphan_ids:
            del self.store.rows[approval_id]
        return len(orphan_ids)

    async def cancel_unattached(self, approval_ids, *, user_id, decided_at):
        count = 0
        for approval_id in approval_ids:
            row = self.store.rows.get(approval_id)
            if row is not None and row.user_id == user_id and row.status == "pending" and row.assistant_message_id is None:
                row.status = "cancelled"
                row.decided_at = decided_at
                count += 1
        return count

    async def has_grant(self, user_id, tool_name):
        return (user_id, tool_name) in self.store.grants

    async def list_grants(self, user_id):
        return [grant for (uid, _name), grant in self.store.grants.items() if uid == user_id]

    async def upsert_grant(self, user_id, tool_name, source_approval_id):
        self.store.grants.setdefault(
            (user_id, tool_name),
            _Grant(user_id=user_id, tool_name=tool_name, source_approval_id=source_approval_id),
        )

    async def delete_grant(self, user_id, tool_name):
        return self.store.grants.pop((user_id, tool_name), None) is not None


@dataclass
class _Grant:
    user_id: int
    tool_name: str
    source_approval_id: UUID
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class _FakeChatRepository:
    """Captures message-part update calls instead of touching chat_history."""

    def __init__(self, calls: list[tuple[str, int, dict[str, Any]]]) -> None:
        self.calls = calls

    async def update_tool_approval_part(self, chat_room_id, message_id, approval):
        self.calls.append((chat_room_id, message_id, approval))
        return True


class _NullAsyncContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc_info):
        return False


class _FakeSession:
    def begin(self):
        return _NullAsyncContext()

    def begin_nested(self):
        return _NullAsyncContext()


class _FakeSessionScope:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, *exc_info):
        return False


def _fake_session_scope():
    return _FakeSessionScope()


def _fake_spec(
    *,
    allows_always: bool = True,
    execute_result: ExecutionOutcome | Exception | None = None,
) -> ToolSpec:
    async def execute(session, user_id, arguments, target_ref) -> ExecutionOutcome:
        if isinstance(execute_result, Exception):
            raise execute_result
        return execute_result or ExecutionOutcome(target_id=1, target_title="Target")

    return ToolSpec(
        name=TOOL_NAME,
        family="memo",
        definition={"type": "function", "function": {"name": TOOL_NAME}},
        budget="write_proposals",
        execute=execute,
        allows_always=allows_always,
    )


# --- services/chat_tool_approval_service.py -----------------------------------------------------


class ChatToolApprovalServiceTests(unittest.TestCase):
    def setUp(self):
        self.store = _FakeStore()
        self.chat_repo_calls: list[tuple[str, int, dict[str, Any]]] = []
        self.specs: dict[str, ToolSpec] = {TOOL_NAME: _fake_spec()}

        for target, value in (
            ("services.chat_tool_approval_service.session_scope", _fake_session_scope),
            (
                "services.chat_tool_approval_service.ChatToolApprovalRepository",
                lambda session: _FakeApprovalRepository(self.store),
            ),
            (
                "services.chat_tool_approval_service.ChatRepository",
                lambda session: _FakeChatRepository(self.chat_repo_calls),
            ),
            ("services.chat_tool_approval_service.get_workspace_tool_spec", lambda name: self.specs.get(name)),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.auth_limit_service = AuthLimitService(redis_client_getter=lambda: None)

    def _seed_pending(
        self,
        *,
        user_id: int = 1,
        chat_room_id: str = "room-1",
        target_ref: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        attached: bool = True,
        message_id: int = 99,
    ) -> _Row:
        row = asyncio.run(
            _FakeApprovalRepository(self.store).insert_approval(
                approval_id=uuid4(),
                user_id=user_id,
                chat_room_id=chat_room_id,
                tool_name=TOOL_NAME,
                arguments={"text": "hi"},
                preview=_preview(),
                target_ref=target_ref if target_ref is not None else {},
                status="pending",
                expires_at=expires_at or (datetime.now(UTC) + timedelta(hours=1)),
            )
        )
        if attached:
            row.assistant_message_id = message_id
        return row

    def _decide(self, row: _Row, decision: str, *, user_id: int | None = None):
        return asyncio.run(
            decide_tool_approval(
                user_id if user_id is not None else row.user_id,
                row.id,
                decision,
                auth_limit_service=self.auth_limit_service,
            )
        )

    # Ownership and the unattached (message_id NULL) window --------------------------------------

    def test_someone_elses_row_reads_as_not_found(self):
        row = self._seed_pending(user_id=1)
        with self.assertRaises(ApiServiceError) as ctx:
            self._decide(row, "approve_once", user_id=2)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.code, "approval_not_found")

    def test_a_row_not_yet_attached_to_a_reply_is_not_actionable(self):
        row = self._seed_pending(attached=False)
        with self.assertRaises(ApiServiceError) as ctx:
            self._decide(row, "approve_once")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.code, "approval_not_found")

    # Idempotency and conflicts -----------------------------------------------------------------

    def test_repeating_the_same_decision_is_idempotent(self):
        row = self._seed_pending()
        first = self._decide(row, "deny")
        second = self._decide(row, "deny")
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "denied")

    def test_a_different_decision_on_a_settled_row_conflicts(self):
        row = self._seed_pending()
        self._decide(row, "deny")
        with self.assertRaises(ApiServiceError) as ctx:
            self._decide(row, "approve_once")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.code, "approval_already_decided")

    # Expiry ---------------------------------------------------------------------------------------

    def test_an_expired_row_settles_to_expired_and_reports_409(self):
        row = self._seed_pending(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        with self.assertRaises(ApiServiceError) as ctx:
            self._decide(row, "approve_once")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.code, "approval_expired")
        self.assertEqual(self.store.rows[row.id].status, "expired")

        # 期限切れ後の再送は、決定に関わらず同じ 409 になる。
        # A repeat after expiry answers 409 the same way regardless of the decision.
        with self.assertRaises(ApiServiceError) as ctx2:
            self._decide(row, "deny")
        self.assertEqual(ctx2.exception.code, "approval_expired")

    # Failure execution ------------------------------------------------------------------------

    def test_a_failed_execution_settles_to_failed_without_raising(self):
        self.specs[TOOL_NAME] = _fake_spec(execute_result=WorkspaceToolError("target_not_found"))
        row = self._seed_pending()
        card = self._decide(row, "approve_once")
        self.assertEqual(card["status"], "failed")
        self.assertEqual(card["result"]["error_code"], "target_not_found")
        self.assertEqual(self.store.rows[row.id].status, "failed")

    # Rate limiting ------------------------------------------------------------------------------

    def test_the_write_limit_blocks_the_run_and_leaves_the_card_pending(self):
        row = self._seed_pending()
        with patch(
            "services.chat_tool_approval_service.consume_chat_tool_write_limit",
            return_value=(False, 42),
        ):
            with self.assertRaises(ChatToolRateLimitedError) as ctx:
                self._decide(row, "approve_once")
        self.assertEqual(ctx.exception.retry_after, 42)
        self.assertEqual(self.store.rows[row.id].status, "pending")

    # Message-part updates -----------------------------------------------------------------------

    def test_deciding_updates_the_saved_messages_card(self):
        row = self._seed_pending(chat_room_id="room-9", message_id=123)
        card = self._decide(row, "approve_once")
        self.assertEqual(len(self.chat_repo_calls), 1)
        chat_room_id, message_id, updated_approval = self.chat_repo_calls[0]
        self.assertEqual(chat_room_id, "room-9")
        self.assertEqual(message_id, 123)
        self.assertEqual(updated_approval["id"], card["id"])
        self.assertEqual(updated_approval["status"], "succeeded")

    # "Always approve" grants -------------------------------------------------------------------

    def test_approve_always_on_a_shared_target_is_rejected(self):
        row = self._seed_pending(target_ref={"shared": True})
        with self.assertRaises(ApiServiceError) as ctx:
            self._decide(row, "approve_always")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.code, "approval_always_not_allowed")
        self.assertEqual(self.store.rows[row.id].status, "pending")

    def test_approve_always_grants_and_revoke_removes_it(self):
        row = self._seed_pending()
        card = self._decide(row, "approve_always")
        self.assertTrue(card["always_allowed"] or card["decision"] == "always")

        grants = asyncio.run(list_auto_approvals(row.user_id))
        self.assertEqual([g["tool_name"] for g in grants], [TOOL_NAME])

        revoked_first = asyncio.run(revoke_auto_approval(row.user_id, TOOL_NAME))
        self.assertTrue(revoked_first)
        self.assertEqual(asyncio.run(list_auto_approvals(row.user_id)), [])

        # 取り消し済みへの再送は冪等（revoked=False で成功扱い）。
        # Revoking again is idempotent: it still succeeds, with revoked False.
        revoked_second = asyncio.run(revoke_auto_approval(row.user_id, TOOL_NAME))
        self.assertFalse(revoked_second)

    # Superseding and cancellation ----------------------------------------------------------------

    def test_a_new_message_supersedes_the_rooms_pending_approvals(self):
        first = self._seed_pending(chat_room_id="room-5", message_id=1)
        second = self._seed_pending(chat_room_id="room-5", message_id=2)
        other_room = self._seed_pending(chat_room_id="room-6", message_id=3)

        count = asyncio.run(supersede_pending_approvals("room-5", first.user_id))

        self.assertEqual(count, 2)
        self.assertEqual(self.store.rows[first.id].status, "superseded")
        self.assertEqual(self.store.rows[second.id].status, "superseded")
        self.assertEqual(self.store.rows[other_room.id].status, "pending")
        self.assertEqual(len(self.chat_repo_calls), 2)

    def test_a_stopped_turn_cancels_only_its_unattached_approvals(self):
        row = self._seed_pending(attached=False)
        count = asyncio.run(cancel_unattached_approvals([str(row.id)], row.user_id))
        self.assertEqual(count, 1)
        self.assertEqual(self.store.rows[row.id].status, "cancelled")

    # Proposal-time helpers -----------------------------------------------------------------------

    def test_create_pending_approval_inserts_a_pending_row(self):
        proposal = Proposal(
            arguments={"text": "hi"},
            preview=_preview(),
            target_ref={},
            target_title="Target",
        )
        card = asyncio.run(
            create_pending_approval(
                user_id=7, chat_room_id="room-7", tool_name=TOOL_NAME, proposal=proposal, untrusted_input=False
            )
        )
        self.assertEqual(card["status"], "pending")
        stored = self.store.rows[UUID(card["id"])]
        self.assertEqual(stored.user_id, 7)
        self.assertIsNone(stored.assistant_message_id)

    def test_execute_auto_approved_settles_a_failed_row_without_raising(self):
        self.specs[TOOL_NAME] = _fake_spec(execute_result=WorkspaceToolError("content_too_long"))
        proposal = Proposal(
            arguments={"text": "hi"}, preview=_preview(), target_ref={}, target_title="Target"
        )
        card = asyncio.run(
            execute_auto_approved(
                user_id=7, chat_room_id="room-7", spec=self.specs[TOOL_NAME], proposal=proposal
            )
        )
        self.assertEqual(card["status"], "failed")
        self.assertEqual(card["decision"], "auto")


# --- blueprints/chat/tool_approvals.py ------------------------------------------------------------


class ChatToolApprovalRouteTests(unittest.IsolatedAsyncioTestCase):
    def _app(self):
        from blueprints.chat import chat_bp

        app = build_session_test_app(chat_bp, secret_key="tool-approval-route-test", include_test_session_route=True)
        app.dependency_overrides[get_auth_limit_service] = lambda: AuthLimitService(redis_client_getter=lambda: None)
        return app

    def _client(self, app) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")

    @asynccontextmanager
    async def _authenticated_client(self, app, *, user_id: int | None = 1, csrf_token: str = "token-1"):
        async with self._client(app) as client:
            payload: dict[str, Any] = {CSRF_SESSION_KEY: csrf_token}
            if user_id is not None:
                payload["user_id"] = user_id
            await client.post("/_test/session", json=payload)
            yield client

    async def test_decide_requires_login(self):
        app = self._app()
        async with self._authenticated_client(app, user_id=None) as client:
            response = await client.post(
                f"/api/chat/tool-approvals/{uuid4()}/decision",
                json={"decision": "approve_once"},
                headers={CSRF_HEADER_NAME: "token-1"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertIn("ログイン", response.json()["error"])

    async def test_decide_rejects_a_missing_csrf_header(self):
        app = self._app()
        async with self._authenticated_client(app) as client:
            response = await client.post(
                f"/api/chat/tool-approvals/{uuid4()}/decision",
                json={"decision": "approve_once"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertIn("CSRF", response.json()["detail"])

    async def test_decide_rejects_a_malformed_approval_id(self):
        app = self._app()
        async with self._authenticated_client(app) as client:
            response = await client.post(
                "/api/chat/tool-approvals/not-a-uuid/decision",
                json={"decision": "approve_once"},
                headers={CSRF_HEADER_NAME: "token-1"},
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "approval_not_found")

    async def test_decide_rejects_an_invalid_decision_value(self):
        app = self._app()
        async with self._authenticated_client(app) as client:
            response = await client.post(
                f"/api/chat/tool-approvals/{uuid4()}/decision",
                json={"decision": "bogus"},
                headers={CSRF_HEADER_NAME: "token-1"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "request.validation_error")

    async def test_decide_returns_the_updated_card_on_success(self):
        app = self._app()
        card = {
            "id": str(uuid4()),
            "tool": TOOL_NAME,
            "family": "memo",
            "status": "succeeded",
            "decision": "once",
            "preview": _preview(),
        }
        async with self._authenticated_client(app) as client:
            with patch(
                "blueprints.chat.tool_approvals.decide_tool_approval", AsyncMock(return_value=card)
            ) as decide:
                response = await client.post(
                    f"/api/chat/tool-approvals/{card['id']}/decision",
                    json={"decision": "approve_once"},
                    headers={CSRF_HEADER_NAME: "token-1"},
                )
        self.assertEqual(response.status_code, 200)
        approval = response.json()["approval"]
        self.assertEqual({key: approval[key] for key in card}, card)
        decide.assert_awaited_once()

    async def test_decide_maps_a_service_conflict_to_its_status_code(self):
        app = self._app()
        async with self._authenticated_client(app) as client:
            with patch(
                "blueprints.chat.tool_approvals.decide_tool_approval",
                AsyncMock(side_effect=ApiServiceError("already decided", 409, code="approval_already_decided")),
            ):
                response = await client.post(
                    f"/api/chat/tool-approvals/{uuid4()}/decision",
                    json={"decision": "approve_once"},
                    headers={CSRF_HEADER_NAME: "token-1"},
                )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "approval_already_decided")

    async def test_decide_is_throttled_by_the_routes_own_rate_limit(self):
        app = self._app()
        async with self._authenticated_client(app) as client:
            with patch("blueprints.chat.tool_approvals.consume_rate_limit", return_value=(False, 0, 17)):
                response = await client.post(
                    f"/api/chat/tool-approvals/{uuid4()}/decision",
                    json={"decision": "approve_once"},
                    headers={CSRF_HEADER_NAME: "token-1"},
                )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), "17")

    async def test_list_auto_approvals_requires_login(self):
        app = self._app()
        async with self._client(app) as client:
            response = await client.get("/api/chat/tool-auto-approvals")
        self.assertEqual(response.status_code, 403)

    async def test_list_auto_approvals_returns_the_services_grants(self):
        app = self._app()
        grants = [{"tool_name": TOOL_NAME, "family": "memo", "created_at": "2026-09-24T00:00:00+00:00"}]
        async with self._authenticated_client(app) as client:
            with patch("blueprints.chat.tool_approvals.list_auto_approvals", AsyncMock(return_value=grants)):
                response = await client.get("/api/chat/tool-auto-approvals")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["grants"], grants)

    async def test_revoke_auto_approval_requires_csrf(self):
        app = self._app()
        async with self._authenticated_client(app) as client:
            response = await client.delete(f"/api/chat/tool-auto-approvals/{TOOL_NAME}")
        self.assertEqual(response.status_code, 403)
        self.assertIn("CSRF", response.json()["detail"])

    async def test_revoke_auto_approval_is_idempotent_when_nothing_was_granted(self):
        app = self._app()
        async with self._authenticated_client(app) as client:
            with patch("blueprints.chat.tool_approvals.revoke_auto_approval", AsyncMock(return_value=False)):
                response = await client.delete(
                    f"/api/chat/tool-auto-approvals/{TOOL_NAME}", headers={CSRF_HEADER_NAME: "token-1"}
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"revoked": False})


if __name__ == "__main__":
    unittest.main()
