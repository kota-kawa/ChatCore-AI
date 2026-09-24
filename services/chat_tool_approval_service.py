"""Approval cards for chat write tools: proposing, deciding, running and retiring them.

チャットの書き込みツールは生成中に実行せず、承認待ち（chat_tool_approvals の1行＝カード1枚）を
保存して回答の末尾にカードを付ける。利用者が承認するとこのサービスが1トランザクションで
実行し、行とメッセージのカードを更新する。「常に承認」を付与済みのツールは、条件を満たせば
提案の時点で実行する（自動承認）。判断の理由は docs/decisions/0013-chat-writes-through-stored-approvals.md。
Chat write tools never run during generation. A pending approval (one chat_tool_approvals row =
one card) is stored and the card is appended to the reply. When the user approves, this service
runs the tool in one transaction and updates both the row and the card on the message. A tool
the user granted "always approve" runs at proposal time when the conditions allow (auto
approval). The reasoning lives in docs/decisions/0013-chat-writes-through-stored-approvals.md.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.async_utils import run_blocking
from services.auth_limits import AuthLimitService, consume_rate_limit
from services.chat_service import save_message_to_db
from services.chat_workspace_tools import get_workspace_tool_spec
from services.chat_workspace_tools.registry import (
    ExecutionOutcome,
    Proposal,
    ToolSpec,
    WorkspaceToolError,
)
from services.db import session_scope
from services.error_messages import (
    ERROR_CHAT_TOOL_WRITE_RATE_LIMITED_TEMPLATE,
    ERROR_TOOL_APPROVAL_ALREADY_DECIDED,
    ERROR_TOOL_APPROVAL_ALWAYS_NOT_ALLOWED,
    ERROR_TOOL_APPROVAL_EXPIRED,
    ERROR_TOOL_APPROVAL_NOT_FOUND,
)
from services.models import ChatToolApproval
from services.repositories.chat_repository import ChatRepository
from services.repositories.chat_tool_approval_repository import ChatToolApprovalRepository
from services.tool_approval_parts import validate_tool_approval_payload

logger = logging.getLogger(__name__)
# 監査ログ。本文や差分は書かず、誰が・どのルームで・どのツールを・どう決めたかだけを残す。
# Audit log: who, in which room, which tool, and how it was decided; never bodies or diffs.
audit_logger = logging.getLogger("chat_core.chat_tools.audit")

TOOL_APPROVAL_TTL = timedelta(hours=24)
# 回答へ結び付かないまま残った行（停止・保存失敗）を片付けるまでの猶予。生成1回より十分長い。
# Grace period before rows never tied to a reply (a stop, a failed save) are cleaned up; well
# beyond one generation.
ORPHAN_APPROVAL_GRACE = timedelta(hours=1)
CHAT_TOOL_WRITE_RATE_KEY = "chat_tool:write:user"
CHAT_TOOL_WRITE_PER_HOUR = 60
CHAT_TOOL_WRITE_WINDOW_SECONDS = 3_600

# 承認 API の決定値と、行に保存する決定値の対応。
# Mapping from the approval API's decision to the decision stored on the row.
_STORED_DECISION = {"approve_once": "once", "approve_always": "always", "deny": "deny"}


class ChatToolRateLimitedError(ApiServiceError):
    """The user's chat write budget is exhausted; the card stays pending."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            ERROR_CHAT_TOOL_WRITE_RATE_LIMITED_TEMPLATE.format(seconds=retry_after),
            429,
            code="chat_tool_rate_limited",
        )
        self.retry_after = retry_after


class _ApprovalAlreadySettledError(Exception):
    """Raised inside a transaction when the row stopped being pending before it was locked."""

    def __init__(self, row: ChatToolApproval) -> None:
        super().__init__(str(row.id))
        self.row = row


def _now() -> datetime:
    return datetime.now(UTC)


def _serialize_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _always_allowed(spec: ToolSpec | None, target_ref: dict[str, Any]) -> bool:
    return bool(spec and spec.allows_always and not target_ref.get("shared"))


# 行からカード（tool_approval パーツの approval）を組み立てる。カードの内容はすべて行が持つ。
# Build the card (a tool_approval part's approval) from a row; the row holds everything on it.
def approval_card(row: ChatToolApproval) -> dict[str, Any]:
    spec = get_workspace_tool_spec(row.tool_name)
    target_ref = dict(row.target_ref or {})
    warnings: list[str] = []
    if target_ref.get("shared"):
        warnings.append("shared_memo")
    if target_ref.get("untrusted_input"):
        warnings.append("untrusted_input_in_turn")
    return validate_tool_approval_payload(
        {
            "id": str(row.id),
            "tool": row.tool_name,
            "family": spec.family if spec else "",
            "status": row.status,
            "decision": row.decision,
            "always_allowed": _always_allowed(spec, target_ref),
            "preview": row.preview,
            "warnings": warnings,
            "expires_at": _serialize_timestamp(row.expires_at),
            "result": row.result,
        }
    )


def _audit(row: ChatToolApproval, *, outcome: str) -> None:
    result = row.result or {}
    audit_logger.info(
        "Chat tool approval %s.",
        outcome,
        extra={
            "chat_tool": row.tool_name,
            "user_id": row.user_id,
            "chat_room_id": row.chat_room_id,
            "approval_id": str(row.id),
            "target_id": result.get("target_id") or (row.target_ref or {}).get("memo_id"),
            "decision": row.decision,
            "outcome": outcome,
            "error_code": result.get("error_code"),
        },
    )


# 実行の失敗を、カードとモデルに見せる理由のコードへ変える。文言はフロントの i18n が持つ。
# Turn an execution failure into the reason code shown on the card and to the model; the
# display text lives in the frontend i18n.
def execution_error_code(exc: Exception) -> str:
    if isinstance(exc, WorkspaceToolError):
        return exc.code
    if isinstance(exc, ApiServiceError):
        if exc.status_code == 404:
            return "target_not_found"
        if exc.status_code == 409:
            return "target_changed"
        if exc.status_code == 400:
            return "invalid_content"
    return "execution_failed"


def _success_result(outcome: ExecutionOutcome) -> dict[str, Any]:
    return {"target_id": outcome.target_id, "target_title": outcome.target_title}


def _run_after_commit(outcome: ExecutionOutcome | None) -> None:
    if outcome is None or outcome.after_commit is None:
        return
    try:
        outcome.after_commit()
    except Exception:
        # 確定済みの書き込みは取り消さない。埋め込みの予約などの後処理だけが漏れる。
        # The committed write stands; only follow-up work such as an embedding is lost.
        logger.exception("Failed to run the follow-up work of an approved chat tool.")


# 書き込みの回数を1人あたりで数える（手動の承認と自動承認の両方）。(許可, 待ち秒数) を返す。
# Count chat writes per user, manual approvals and auto approvals alike; returns
# (allowed, retry_after_seconds).
def consume_chat_tool_write_limit(
    user_id: int,
    *,
    service: AuthLimitService | None = None,
) -> tuple[bool, int]:
    allowed, _, retry_after = consume_rate_limit(
        CHAT_TOOL_WRITE_RATE_KEY,
        str(user_id),
        limit=CHAT_TOOL_WRITE_PER_HOUR,
        window_seconds=CHAT_TOOL_WRITE_WINDOW_SECONDS,
        service=service,
    )
    return allowed, int(retry_after or 0)


# Proposal time (called from the generation worker) ---------------------------


async def has_auto_approval(user_id: int, tool_name: str) -> bool:
    async with session_scope() as db:
        return await ChatToolApprovalRepository(db).has_grant(user_id, tool_name)


def _proposal_target_ref(proposal: Proposal, *, untrusted_input: bool) -> dict[str, Any]:
    target_ref = dict(proposal.target_ref)
    if untrusted_input:
        target_ref["untrusted_input"] = True
    return target_ref


async def create_pending_approval(
    *,
    user_id: int,
    chat_room_id: str,
    tool_name: str,
    proposal: Proposal,
    untrusted_input: bool,
) -> dict[str, Any]:
    now = _now()
    async with session_scope() as db, db.begin():
        row = await ChatToolApprovalRepository(db).insert_approval(
            approval_id=uuid4(),
            user_id=user_id,
            chat_room_id=chat_room_id,
            tool_name=tool_name,
            arguments=proposal.arguments,
            preview=proposal.preview,
            target_ref=_proposal_target_ref(proposal, untrusted_input=untrusted_input),
            status="pending",
            expires_at=now + TOOL_APPROVAL_TTL,
        )
        card = approval_card(row)
    _audit(row, outcome="proposed")
    return card


# 自動承認: 提案をその場で独立したトランザクションで実行し、決定済みの行（decision=auto）を残す。
# 失敗しても例外にせず、失敗のカードを返す。
# Auto approval: run the proposal on the spot in its own transaction and keep a settled row
# (decision=auto). A failure is not raised; it comes back as a failed card.
async def execute_auto_approved(
    *,
    user_id: int,
    chat_room_id: str,
    spec: ToolSpec,
    proposal: Proposal,
) -> dict[str, Any]:
    now = _now()
    approval_id = uuid4()
    target_ref = _proposal_target_ref(proposal, untrusted_input=False)
    outcome: ExecutionOutcome | None = None
    async with session_scope() as db, db.begin():
        repo = ChatToolApprovalRepository(db)
        try:
            async with db.begin_nested():
                outcome = await _execute(spec, db, user_id, proposal.arguments, target_ref)
            status, result = "succeeded", _success_result(outcome)
        except (WorkspaceToolError, ApiServiceError) as exc:
            outcome = None
            status, result = "failed", {"error_code": execution_error_code(exc)}
        row = await repo.insert_approval(
            approval_id=approval_id,
            user_id=user_id,
            chat_room_id=chat_room_id,
            tool_name=spec.name,
            arguments=proposal.arguments,
            preview=proposal.preview,
            target_ref=target_ref,
            status=status,
            decision="auto",
            result=result,
            expires_at=now + TOOL_APPROVAL_TTL,
            decided_at=now,
        )
        card = approval_card(row)
    _run_after_commit(outcome)
    _audit(row, outcome=status)
    return card


async def _execute(
    spec: ToolSpec,
    session: AsyncSession,
    user_id: int,
    arguments: dict[str, Any],
    target_ref: dict[str, Any],
) -> ExecutionOutcome:
    if spec.execute is None:
        raise WorkspaceToolError("execution_failed")
    return await spec.execute(session, user_id, dict(arguments), dict(target_ref))


# Reply persistence and lifecycle ---------------------------------------------


# 回答の保存と、承認行への回答 ID の結び付けを1トランザクションで行う。結び付いた行だけが
# 承認 API から操作できる。
# Save the reply and tie the approval rows to it in one transaction; only tied rows can be
# acted on through the approval API.
async def save_assistant_message_with_approvals(
    *,
    chat_room_id: str,
    user_id: int,
    message: str,
    parent_id: int | None,
    message_parts: list[dict[str, Any]] | None,
    web_search_context: list[dict[str, Any]] | None,
    approval_ids: Sequence[str],
) -> int | None:
    async with session_scope() as db, db.begin():
        message_id = await save_message_to_db(
            chat_room_id,
            message,
            "assistant",
            None,
            parent_id,
            message_parts,
            None,
            web_search_context,
            session=db,
        )
        if message_id is not None:
            await ChatToolApprovalRepository(db).attach_message(
                [UUID(approval_id) for approval_id in approval_ids],
                user_id=user_id,
                chat_room_id=chat_room_id,
                message_id=message_id,
            )
    return message_id


# 新しい発言・再生成の前に、そのルームで保存済みの承認待ちを無効（superseded）にし、
# 回答へ結び付かないまま猶予を過ぎた行を片付ける。
# Before a new message or a regeneration, supersede the room's pending approvals on saved
# replies and clean up rows that never reached a reply within the grace period.
async def supersede_pending_approvals(chat_room_id: str, user_id: int) -> int:
    now = _now()
    async with session_scope() as db, db.begin():
        repo = ChatToolApprovalRepository(db)
        rows = await repo.settle_pending_in_room(
            chat_room_id,
            user_id=user_id,
            status="superseded",
            decided_at=now,
        )
        chat_repo = ChatRepository(db)
        for row in rows:
            if row.assistant_message_id is not None:
                await chat_repo.update_tool_approval_part(row.chat_room_id, row.assistant_message_id, approval_card(row))
        await repo.delete_orphans_in_room(
            chat_room_id,
            user_id=user_id,
            created_before=now - ORPHAN_APPROVAL_GRACE,
        )
    for row in rows:
        _audit(row, outcome="superseded")
    return len(rows)


# 停止した生成が残した承認待ちを取り消す。
# Cancel the pending approvals a stopped generation left behind.
async def cancel_unattached_approvals(approval_ids: Sequence[str], user_id: int) -> int:
    if not approval_ids:
        return 0
    async with session_scope() as db, db.begin():
        return await ChatToolApprovalRepository(db).cancel_unattached(
            [UUID(approval_id) for approval_id in approval_ids],
            user_id=user_id,
            decided_at=_now(),
        )


# Decisions (the approval API) --------------------------------------------------


# 決定済みのカードへの再送は、同じ決定なら冪等に同じカードを返し、違えば衝突にする。
# A repeat on a settled card returns the same card when the decision matches and conflicts
# otherwise.
def _settled_card(row: ChatToolApproval, decision: str) -> dict[str, Any]:
    if row.status == "expired":
        raise ApiServiceError(ERROR_TOOL_APPROVAL_EXPIRED, 409, code="approval_expired")
    if row.decision == decision:
        return approval_card(row)
    raise ApiServiceError(ERROR_TOOL_APPROVAL_ALREADY_DECIDED, 409, code="approval_already_decided")


def _approval_not_found() -> ResourceNotFoundError:
    return ResourceNotFoundError(ERROR_TOOL_APPROVAL_NOT_FOUND, code="approval_not_found")


def _is_expired(row: ChatToolApproval, now: datetime) -> bool:
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= now


# 承認待ちの行をロックして決定を確定し、メッセージのカードも同じトランザクションで更新する。
# 承認なら実行を SAVEPOINT の中で行い、失敗したら実行だけを戻して failed を記録する。
# Lock a pending row, settle it, and update the card on the message in the same transaction.
# An approval runs the tool inside a SAVEPOINT; on failure only the run is rolled back and the
# row records failed.
async def _settle_locked(
    approval_id: UUID,
    user_id: int,
    *,
    decision: str | None,
    spec: ToolSpec | None,
    now: datetime,
) -> tuple[ChatToolApproval, dict[str, Any], ExecutionOutcome | None]:
    """Settle one pending row: ``decision`` None expires it, "deny" denies it, else it runs."""
    outcome: ExecutionOutcome | None = None
    async with session_scope() as db, db.begin():
        repo = ChatToolApprovalRepository(db)
        row = await repo.get_actionable(approval_id, user_id, for_update=True)
        if row is None:
            raise _approval_not_found()
        if row.status != "pending":
            raise _ApprovalAlreadySettledError(row)
        stored_decision = decision
        if decision is None:
            status, result = "expired", None
        elif decision == "deny":
            status, result = "denied", None
        else:
            assert spec is not None
            try:
                async with db.begin_nested():
                    outcome = await _execute(spec, db, user_id, row.arguments, row.target_ref or {})
                status, result = "succeeded", _success_result(outcome)
            except (WorkspaceToolError, ApiServiceError) as exc:
                outcome = None
                status, result = "failed", {"error_code": execution_error_code(exc)}
        await repo.settle(row, status=status, decision=stored_decision, result=result, decided_at=now)
        card = approval_card(row)
        if row.assistant_message_id is not None:
            await ChatRepository(db).update_tool_approval_part(row.chat_room_id, row.assistant_message_id, card)
        if status == "succeeded" and stored_decision == "always":
            await repo.upsert_grant(user_id, row.tool_name, row.id)
    return row, card, outcome


# 承認 API の本体。順序は「所有者で絞る → 決定済み → 期限 → 常に承認の可否 → 書き込みの上限 →
# 実行」。決定済みの冪等・衝突と期限切れは、ロックの前後どちらで判明しても同じ応答にする。
# The approval API's core. Order: scope by owner → already settled → expiry → whether "always"
# is allowed → the write limit → run. Idempotent repeats, conflicts and expiry answer the same
# way whether they are found before or after the lock.
async def decide_tool_approval(
    user_id: int,
    approval_id: UUID,
    requested_decision: str,
    *,
    auth_limit_service: AuthLimitService | None = None,
) -> dict[str, Any]:
    decision = _STORED_DECISION[requested_decision]
    async with session_scope() as db:
        row = await ChatToolApprovalRepository(db).get_actionable(approval_id, user_id)
    if row is None:
        raise _approval_not_found()
    if row.status != "pending":
        return _settled_card(row, decision)
    now = _now()
    if _is_expired(row, now):
        try:
            expired_row, _, _ = await _settle_locked(approval_id, user_id, decision=None, spec=None, now=now)
        except _ApprovalAlreadySettledError as settled:
            return _settled_card(settled.row, decision)
        _audit(expired_row, outcome="expired")
        raise ApiServiceError(ERROR_TOOL_APPROVAL_EXPIRED, 409, code="approval_expired")

    spec = get_workspace_tool_spec(row.tool_name)
    if decision == "always" and not _always_allowed(spec, dict(row.target_ref or {})):
        raise ApiServiceError(ERROR_TOOL_APPROVAL_ALWAYS_NOT_ALLOWED, 400, code="approval_always_not_allowed")
    if decision != "deny":
        if spec is None:
            raise _approval_not_found()
        allowed, retry_after = await run_blocking(
            consume_chat_tool_write_limit,
            user_id,
            service=auth_limit_service,
        )
        if not allowed:
            raise ChatToolRateLimitedError(retry_after)

    try:
        settled_row, card, outcome = await _settle_locked(approval_id, user_id, decision=decision, spec=spec, now=now)
    except _ApprovalAlreadySettledError as settled:
        return _settled_card(settled.row, decision)
    _run_after_commit(outcome)
    _audit(settled_row, outcome=settled_row.status)
    return card


# "Always approve" grants ------------------------------------------------------


async def list_auto_approvals(user_id: int) -> list[dict[str, Any]]:
    async with session_scope() as db:
        grants = await ChatToolApprovalRepository(db).list_grants(user_id)
    listed: list[dict[str, Any]] = []
    for grant in grants:
        spec = get_workspace_tool_spec(grant.tool_name)
        if spec is None:
            continue
        listed.append(
            {
                "tool_name": grant.tool_name,
                "family": spec.family,
                "created_at": _serialize_timestamp(grant.created_at) or "",
            }
        )
    return listed


async def revoke_auto_approval(user_id: int, tool_name: str) -> bool:
    async with session_scope() as db, db.begin():
        revoked = await ChatToolApprovalRepository(db).delete_grant(user_id, tool_name)
    if revoked:
        audit_logger.info(
            "Chat tool auto approval revoked.",
            extra={"chat_tool": tool_name, "user_id": user_id, "outcome": "revoked"},
        )
    return revoked
