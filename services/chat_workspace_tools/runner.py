"""Runs one workspace tool call inside the chat generation loop.

生成ループ（同期のワーカースレッド）から呼ばれ、非同期の DB 処理は asyncio.run で橋渡しする
（services/chat_generation.py の検索系ツールと同じ進め方）。読み取りは結果を根拠として登録し、
書き込みは提案を作って承認待ちにするか、「常に承認」の条件を満たせばその場で実行する。
Called from the generation loop (a synchronous worker thread); async database work is bridged
with asyncio.run, the same way the lookup tools in services/chat_generation.py do it. Reads are
registered as evidence; writes become a pending approval, or run on the spot when the "always
approve" conditions hold.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from services.chat_agent_budget import READ_MESSAGE_MAX_CHARS
from services.chat_generation_turn import ChatTurnRunState
from services.chat_tool_approval_service import (
    cancel_unattached_approvals,
    consume_chat_tool_write_limit,
    create_pending_approval,
    execute_auto_approved,
    has_auto_approval,
)

from .memo import MEMO_APPEND_TOOL_NAME, MEMO_EDIT_TOOL_NAME, MEMO_READ_TOOL_NAME
from .registry import (
    ChatWorkspaceToolbox,
    Proposal,
    ToolSpec,
    WorkspaceToolArgumentError,
    WorkspaceToolError,
    parse_tool_arguments,
)

logger = logging.getLogger(__name__)

# 承認待ちになった書き込みについてモデルへ返す文。実行していないことを明示する。
# What the model hears about a write left for approval: it has not run.
AWAITING_APPROVAL_MESSAGE = "Not executed. The user will approve or reject it on a card."

# 理由のコードに添えてモデルへ返す説明。カードの文言はフロントの i18n が持つ。
# Explanations sent to the model alongside a reason code; the card's text lives in the frontend.
_ERROR_HINTS = {
    "target_not_found": "The memo was not found. Use memo_list or memo_search to get a valid memo_id.",
    "content_too_long": "The memo would exceed its maximum length. Shorten the text.",
    "target_changed": "The memo changed in the meantime. Read it again before proposing a change.",
    "target_shared": "The memo became shared in the meantime, so it was not changed.",
}


class WorkspaceToolRunner:
    def __init__(
        self,
        toolbox: ChatWorkspaceToolbox,
        *,
        publish: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self._toolbox = toolbox
        self._publish = publish
        self._read_memo_ids: set[int] = set()

    def run(self, state: ChatTurnRunState, tool_call: dict[str, Any]) -> dict[str, Any]:
        function = tool_call.get("function") or {}
        spec = self._toolbox.spec(str(function.get("name")))
        raw_arguments = function.get("arguments", "{}")
        if spec.is_write:
            return self._propose(state, spec, raw_arguments)
        return self._read(state, spec, raw_arguments)

    # Reads -------------------------------------------------------------------

    def _read(self, state: ChatTurnRunState, spec: ToolSpec, raw_arguments: Any) -> dict[str, Any]:
        budget = state.budget
        telemetry = state.telemetry
        uses_reads = spec.budget == "reads"
        if (budget.reads_exhausted if uses_reads else budget.tool_calls_exhausted):
            return {
                "status": "step_limit_reached",
                "message": "The limit for this tool has been reached. Use what was already read.",
            }
        if uses_reads:
            budget.start_read_call()
            max_chars = budget.read_message_limit
        else:
            budget.start_tool_call()
            max_chars = READ_MESSAGE_MAX_CHARS
        telemetry.tool_calls = budget.tool_calls
        telemetry.workspace_read_calls += 1
        progress = {"tool": spec.name, "step": budget.step, "max_steps": budget.max_steps}
        self._publish("workspace_tool_started", progress)

        payload: dict[str, Any]
        query = ""
        try:
            arguments = parse_tool_arguments(raw_arguments)
            assert spec.read is not None
            result = asyncio.run(spec.read(self._toolbox.user_id, arguments, max_chars))
        except WorkspaceToolArgumentError as exc:
            telemetry.workspace_invalid_arguments += 1
            payload = {"status": "invalid_arguments", "problems": list(exc.problems)}
        except WorkspaceToolError as exc:
            payload = self._error_payload(exc.code)
        except Exception:
            logger.exception("Chat workspace tool failed (tool=%s).", spec.name)
            self._publish("workspace_tool_failed", progress)
            state.turn_state.record_search(tool_name=spec.name, status="failed")
            return {"status": "failed", "message": f"{spec.name} failed."}
        else:
            payload = result.payload
            query = result.query
            if spec.name == MEMO_READ_TOOL_NAME and payload.get("status") == "ok":
                memos = payload.get("memos")
                if isinstance(memos, list):
                    self._read_memo_ids.update(
                        memo_id
                        for memo in memos
                        if isinstance(memo, dict)
                        and isinstance((memo_id := memo.get("id")), int)
                        and not isinstance(memo_id, bool)
                        and memo_id > 0
                    )
            evidence_refs = state.evidence_store.add_reference_payload(
                payload,
                source_type=spec.family,
                query=query,
            )
            state.turn_state.record_search(
                tool_name=spec.name,
                query=query,
                evidence_refs=evidence_refs,
                status="ok",
            )
        if payload.get("status") != "ok":
            state.turn_state.record_search(tool_name=spec.name, query=query, status=str(payload["status"]))
        if uses_reads:
            budget.consume_read_chars(len(json.dumps(payload, ensure_ascii=False)))
            telemetry.evidence_read_count = budget.read_calls
            telemetry.read_budget_consumed = budget.read_chars
        self._publish("workspace_tool_completed", {**progress, "status": payload.get("status")})
        return payload

    # Write proposals -----------------------------------------------------------

    def _propose(self, state: ChatTurnRunState, spec: ToolSpec, raw_arguments: Any) -> dict[str, Any]:
        budget = state.budget
        telemetry = state.telemetry
        if budget.write_proposals_exhausted:
            return {
                "status": "step_limit_reached",
                "message": "The limit of proposed changes for this reply has been reached.",
            }
        budget.start_write_proposal()
        telemetry.workspace_write_proposals += 1
        progress = {"tool": spec.name, "step": budget.step, "max_steps": budget.max_steps}
        self._publish("workspace_tool_started", progress)
        try:
            arguments = parse_tool_arguments(raw_arguments)
            unread_memo_id = self._unread_memo_id(spec, arguments)
            if unread_memo_id is not None:
                message = "Read the target memo with memo_read before proposing an append or edit."
                state.turn_state.record_search(
                    tool_name=spec.name,
                    query=f"memo:{unread_memo_id}",
                    status="read_required",
                )
                self._publish(
                    "workspace_tool_completed",
                    {**progress, "status": "read_required"},
                )
                return {"status": "read_required", "message": message}
            assert spec.propose is not None
            proposal = asyncio.run(spec.propose(self._toolbox.user_id, arguments))
        except WorkspaceToolArgumentError as exc:
            telemetry.workspace_invalid_arguments += 1
            state.turn_state.record_search(tool_name=spec.name, status="invalid_arguments")
            self._publish("workspace_tool_completed", {**progress, "status": "invalid_arguments"})
            return {"status": "invalid_arguments", "problems": list(exc.problems)}
        except WorkspaceToolError as exc:
            state.turn_state.record_search(tool_name=spec.name, status=exc.code)
            self._publish("workspace_tool_completed", {**progress, "status": "error"})
            return self._error_payload(exc.code)
        except Exception:
            logger.exception("Preparing a chat workspace proposal failed (tool=%s).", spec.name)
            state.turn_state.record_search(tool_name=spec.name, status="failed")
            self._publish("workspace_tool_failed", progress)
            return {"status": "failed", "message": "The change could not be prepared."}

        try:
            if self._may_auto_approve(state, spec, proposal):
                card = asyncio.run(
                    execute_auto_approved(
                        user_id=self._toolbox.user_id,
                        chat_room_id=self._toolbox.chat_room_id,
                        spec=spec,
                        proposal=proposal,
                    )
                )
                telemetry.workspace_auto_executions += 1
            else:
                card = asyncio.run(
                    create_pending_approval(
                        user_id=self._toolbox.user_id,
                        chat_room_id=self._toolbox.chat_room_id,
                        tool_name=spec.name,
                        proposal=proposal,
                        untrusted_input=state.untrusted_input_ingested,
                    )
                )
        except Exception:
            logger.exception("Saving a chat workspace proposal failed (tool=%s).", spec.name)
            state.turn_state.record_search(tool_name=spec.name, status="failed")
            self._publish("workspace_tool_failed", progress)
            return {"status": "failed", "message": "The change could not be prepared."}

        state.tool_approval_parts.append(card)
        state.turn_state.record_search(tool_name=spec.name, query=proposal.target_title, status=card["status"])
        # 承認待ちなら tool_approval_prepared、自動承認で実行したなら成否を completed / failed で伝える。
        # A pending card announces tool_approval_prepared; an auto-approved run reports completed or
        # failed.
        if card["status"] == "pending":
            self._publish("tool_approval_prepared", {"tool": spec.name, "approval_id": card["id"]})
        elif card["status"] == "succeeded":
            self._publish("workspace_tool_completed", {**progress, "status": "executed", "approval_id": card["id"]})
        else:
            self._publish("workspace_tool_failed", {**progress, "approval_id": card["id"]})
        if card["status"] == "pending":
            # 承認待ちの回答で、何が承認待ちかをサーバーの側で要約して渡す（JSON の値に閉じ込め、題名で
            # 囲みのタグを閉じられないよう "<" もエスケープする）。
            # The server's own summary of what awaits approval, kept inside JSON values ("<" escaped so a
            # title cannot close the surrounding tag).
            state.approval_pending_summaries.append(
                json.dumps({"tool": spec.name, "target": proposal.target_title}, ensure_ascii=False).replace(
                    "<", "\\u003c"
                )
            )
            return {"status": "awaiting_user_approval", "approval_id": card["id"], "message": AWAITING_APPROVAL_MESSAGE}
        result = card.get("result") or {}
        if card["status"] == "succeeded":
            return {"status": "executed", "result": result}
        return self._error_payload(str(result.get("error_code") or "execution_failed"))

    def _unread_memo_id(self, spec: ToolSpec, arguments: dict[str, Any]) -> int | None:
        if spec.name not in {MEMO_APPEND_TOOL_NAME, MEMO_EDIT_TOOL_NAME}:
            return None
        raw_memo_id = arguments.get("memo_id")
        if isinstance(raw_memo_id, bool):
            return None
        if isinstance(raw_memo_id, int):
            memo_id = raw_memo_id
        elif isinstance(raw_memo_id, str) and raw_memo_id.strip().isdecimal():
            memo_id = int(raw_memo_id.strip())
        elif isinstance(raw_memo_id, float) and raw_memo_id.is_integer():
            memo_id = int(raw_memo_id)
        else:
            return None
        if memo_id <= 0 or memo_id in self._read_memo_ids:
            return None
        return memo_id

    # 「常に承認」を付与済みで、対象が共有中でなく、このターンで外部の内容を読んでおらず、
    # 書き込みの上限にも達していないときだけ、提案の時点で実行する。
    # Run at proposal time only when "always approve" is granted, the target is not shared,
    # the turn has read no external content, and the write limit still allows it.
    def _may_auto_approve(self, state: ChatTurnRunState, spec: ToolSpec, proposal: Proposal) -> bool:
        if not spec.allows_always or proposal.shared:
            return False
        if not asyncio.run(has_auto_approval(self._toolbox.user_id, spec.name)):
            return False
        if state.untrusted_input_ingested:
            state.telemetry.auto_approval_suppressed_by_untrusted_input = True
            return False
        allowed, _ = consume_chat_tool_write_limit(self._toolbox.user_id)
        return allowed

    @staticmethod
    def _error_payload(code: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": "error", "error_code": code}
        hint = _ERROR_HINTS.get(code)
        if hint:
            payload["message"] = hint
        return payload

    # 停止・失敗したターンでは、未実行の承認待ちを取り消し（cancelled）、カードもそれに合わせる。
    # When a turn stops or fails, cancel the approvals still pending and mark their cards to match.
    def settle_after_interruption(self, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        pending_ids = [str(card["id"]) for card in cards if card.get("status") == "pending"]
        if pending_ids:
            try:
                asyncio.run(cancel_unattached_approvals(pending_ids, self._toolbox.user_id))
            except Exception:
                logger.exception("Failed to cancel the pending approvals of an interrupted turn.")
        return [{**card, "status": "cancelled"} if card.get("status") == "pending" else card for card in cards]
