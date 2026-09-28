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
from dataclasses import replace
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

from .memo import MEMO_APPEND_TOOL_NAME, MEMO_EDIT_TOOL_NAME, MEMO_READ_TOOL_NAME, MEMO_TOOL_FAMILY
from .private_overlap import PrivateTextTracker, extract_private_texts
from .prompts import (
    MY_PROMPT_READ_TOOL_NAME,
    MY_SKILL_READ_TOOL_NAME,
    PROMPTS_TOOL_FAMILY,
    PUBLIC_PROMPT_EDIT_TOOL_NAME,
    PUBLISH_PROMPT_TOOL_NAME,
)
from .registry import (
    ChatWorkspaceToolbox,
    Proposal,
    ToolSpec,
    WorkspaceToolArgumentError,
    WorkspaceToolError,
    parse_tool_arguments,
)

# 提案の中身のうち、非公開の混入を確かめる対象にする文字列フィールド。
# The proposal fields checked for private-content overlap.
_PUBLISH_PROMPT_OVERLAP_FIELDS = (
    "title", "content", "description", "input_examples", "output_examples", "ai_model"
)
# get_evidence の再読み取りで「自分自身のデータ」として扱う family。ここに無い family
# （公開データ）は外部の内容として扱われる（services/chat_generation.py も参照）。
# Families treated as "the user's own data" for a later get_evidence re-read; any family not
# listed here (public data) is treated as external content (see services/chat_generation.py).
_PRIVATE_TEXT_FAMILIES = frozenset({MEMO_TOOL_FAMILY, PROMPTS_TOOL_FAMILY})

logger = logging.getLogger(__name__)

# 承認待ちになった書き込みについてモデルへ返す文。実行していないことを明示する。
# What the model hears about a write left for approval: it has not run.
AWAITING_APPROVAL_MESSAGE = "Not executed. The user will approve or reject it on a card."

# 理由のコードに添えてモデルへ返す説明。カードの文言はフロントの i18n が持つ。
# Explanations sent to the model alongside a reason code; the card's text lives in the frontend.
_ERROR_HINTS = {
    "target_not_found": "The target was not found. Re-check the id with the matching list or search tool.",
    "content_too_long": "The memo would exceed its maximum length. Shorten the text.",
    "target_changed": "The target changed in the meantime. Read or list it again before proposing a change.",
    "target_shared": "The memo became shared in the meantime, so it was not changed.",
    "name_conflict": "A prompt, Task or Skill with that name already exists. Use a different name.",
    "prompt_rate_limited": "Too many prompts were published recently. Try again later.",
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
        # 非公開の内容が publish_prompt の提案に混入していないか確かめるための追跡。
        # llm_profile_context を種にし、このターンで読んだ自分自身のデータを足していく。
        # Tracks private content to check against a publish_prompt proposal; seeded with
        # llm_profile_context and grown with the user's own data read during this turn.
        self._private_texts = PrivateTextTracker(seed=toolbox.llm_profile_context)

    def run(self, state: ChatTurnRunState, tool_call: dict[str, Any]) -> dict[str, Any]:
        function = tool_call.get("function") or {}
        spec = self._toolbox.spec(str(function.get("name")))
        raw_arguments = function.get("arguments", "{}")
        result = self._propose(state, spec, raw_arguments) if spec.is_write else self._read(state, spec, raw_arguments)
        state.telemetry.record_workspace_tool_result(spec.name, result.get("status"))
        return result

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
            if spec.family in _PRIVATE_TEXT_FAMILIES:
                self._track_private_text_result(spec.name, payload)
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

    def _track_private_text_result(self, tool_name: str, payload: dict[str, Any]) -> None:
        if tool_name == MY_PROMPT_READ_TOOL_NAME:
            entry = payload.get("task")
            resource_type, id_key = "task", "task_id"
        elif tool_name == MY_SKILL_READ_TOOL_NAME:
            entry = payload.get("skill")
            resource_type, id_key = "skill", "skill_id"
        else:
            entry = None
            resource_type, id_key = "", ""

        if isinstance(entry, dict):
            resource_id = entry.get(id_key)
            section = entry.get("section")
            start = entry.get("start")
            content = entry.get("content")
            if (
                isinstance(resource_id, int)
                and not isinstance(resource_id, bool)
                and isinstance(section, str)
                and isinstance(start, int)
                and not isinstance(start, bool)
                and isinstance(content, str)
            ):
                self._private_texts.add_chunk(
                    f"{resource_type}:{resource_id}:{section}", start, content
                )
                return

        for text in extract_private_texts(payload):
            self._private_texts.add(text)

    # Write proposals -----------------------------------------------------------

    def _propose(self, state: ChatTurnRunState, spec: ToolSpec, raw_arguments: Any) -> dict[str, Any]:
        budget = state.budget
        telemetry = state.telemetry
        if budget.write_proposals_exhausted:
            return {
                "status": "step_limit_reached",
                "message": "The limit of proposed changes for this reply has been reached.",
            }
        # 読んでいないメモへの追記・書き換えは提案にならないので、提案の予算も件数も使わせない。
        # An append or edit on an unread memo never becomes a proposal, so it spends neither the
        # proposal budget nor the proposal count.
        try:
            arguments = parse_tool_arguments(raw_arguments)
        except WorkspaceToolArgumentError:
            arguments = None
        progress = {"tool": spec.name, "step": budget.step, "max_steps": budget.max_steps}
        self._publish("workspace_tool_started", progress)
        unread_memo_id = self._unread_memo_id(spec, arguments) if arguments is not None else None
        if unread_memo_id is not None:
            state.turn_state.record_search(
                tool_name=spec.name,
                query=f"memo:{unread_memo_id}",
                status="read_required",
            )
            self._publish("workspace_tool_completed", {**progress, "status": "read_required"})
            return {
                "status": "read_required",
                "message": "Read the target memo with memo_read before proposing an append or edit.",
            }
        budget.start_write_proposal()
        telemetry.workspace_write_proposals += 1
        try:
            if arguments is None:
                arguments = parse_tool_arguments(raw_arguments)
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

        if spec.name in {PUBLISH_PROMPT_TOOL_NAME, PUBLIC_PROMPT_EDIT_TOOL_NAME}:
            proposal = self._flag_private_overlap(proposal)

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

    # このターンで読んだ非公開の内容が公開投稿の提案へ 50 字以上そのまま混入していないか確かめる。
    # 見つかっても提案は止めず、承認カードへ警告として出すだけにする（services/response_models.py
    # の private_text_in_public_post と ToolApprovalDecisionRequest.acknowledge_warnings を参照）。
    # Check whether private content read this turn reappears, 50+ characters verbatim, inside a
    # public prompt proposal. A match never stops the proposal; it only adds a warning to the
    # card (see private_text_in_public_post in services/response_models.py and
    # ToolApprovalDecisionRequest.acknowledge_warnings).
    def _flag_private_overlap(self, proposal: Proposal) -> Proposal:
        candidate = " ".join(
            str(proposal.preview.get(field) or "") for field in _PUBLISH_PROMPT_OVERLAP_FIELDS
        )
        matches = self._private_texts.find_overlaps(candidate)
        if not matches:
            return proposal
        return replace(proposal, target_ref={**proposal.target_ref, "private_overlap_excerpts": matches})

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
