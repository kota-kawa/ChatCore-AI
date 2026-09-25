"""チャットの書き込みツール（メモ）とその実行境界（WorkspaceToolRunner）の契約を検証する。

Verifies the contract of the chat workspace tools (memo) and their execution boundary
(WorkspaceToolRunner): argument validation, read dispatch, write proposals, auto approval
(and its suppression once external content was read), budget exhaustion and telemetry.

書き込みツールの実行そのもの（DB へのコミット）は services/chat_tool_approval_service.py が
テスト済みの API 側で担保する。ここでは提案の組み立てとランナーの分岐だけを見る。
Executing a write (the DB commit) is covered on the approval-API side
(tests/unit/test_chat_tool_approval_api.py). This file only exercises proposal building and the
runner's branching.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from services.chat_agent_budget import AgentStepBudget
from services.chat_generation import ChatGenerationJob
from services.chat_generation_telemetry import ChatGenerationTelemetry
from services.chat_generation_turn import ChatTurnRunState
from services.chat_turn_state import TurnStateUpdateFilter
from services.chat_workspace_tools import build_workspace_toolbox, get_workspace_tool_spec
from services.chat_workspace_tools.memo import (
    MEMO_APPEND_TOOL_NAME,
    MEMO_CREATE_TOOL_NAME,
    MEMO_EDIT_TOOL_NAME,
    MEMO_LIST_TOOL_NAME,
    MEMO_READ_TOOL_NAME,
    MEMO_SEARCH_TOOL_NAME,
    MEMO_TOOL_SPECS,
    MemoAppendArguments,
    MemoCreateArguments,
    MemoEditArguments,
    _propose_memo_append,
    _propose_memo_create,
    _propose_memo_edit,
)
from services.chat_workspace_tools.registry import (
    ChatWorkspaceToolbox,
    Proposal,
    ReadResult,
    ToolSpec,
    WorkspaceToolArgumentError,
    WorkspaceToolError,
    parse_tool_arguments,
    validation_problems,
)
from services.chat_workspace_tools.runner import AWAITING_APPROVAL_MESSAGE, WorkspaceToolRunner
from services.mcp_memo_service import McpMemoDetail
from services.request_models import MAX_MEMO_STORED_CONTENT_LENGTH
from services.tool_approval_parts import TOOL_APPROVAL_PART_TYPE

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "memo_agent_edit_cases.json"


def _tool_call(name: str, **arguments) -> dict:
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def _make_state(**overrides) -> ChatTurnRunState:
    defaults = {
        "chunks": [],
        "telemetry": ChatGenerationTelemetry(),
        "budget": AgentStepBudget(max_llm_turns=8, max_tool_calls=6),
        "page_fetch_budget": MagicMock(),
        "evidence_context_budget": MagicMock(),
        "evidence_store": MagicMock(),
        "web_page_reader": MagicMock(),
        "turn_state": MagicMock(),
        "turn_base_messages": [],
        "latest_user_message": "",
        "selected_web_search_images": [],
        "continuation_state_filter": TurnStateUpdateFilter(),
    }
    defaults["evidence_store"].add_reference_payload = MagicMock(return_value=())
    defaults.update(overrides)
    return ChatTurnRunState(**defaults)


def _fake_read_spec(
    *,
    allows_always: bool = False,
    name: str = "fake_read",
    memo_ids: tuple[int, ...] = (),
) -> ToolSpec:
    async def read(user_id: int, arguments: dict, max_chars: int) -> ReadResult:
        return ReadResult(
            payload={"status": "ok", "echo": arguments, "memos": [{"id": memo_id} for memo_id in memo_ids]},
            query="fake-query",
        )

    return ToolSpec(
        name=name,
        family="memo",
        definition={"type": "function", "function": {"name": name}},
        budget="reads",
        read=read,
        allows_always=allows_always,
    )


def _fake_write_spec(
    *,
    allows_always: bool = True,
    shared: bool = False,
    raise_error: Exception | None = None,
    name: str = "fake_write",
):
    async def propose(user_id: int, arguments: dict) -> Proposal:
        if raise_error is not None:
            raise raise_error
        return Proposal(
            arguments=dict(arguments),
            preview={"kind": name, **arguments},
            target_ref={"shared": shared},
            target_title="Target",
            shared=shared,
        )

    return ToolSpec(
        name=name,
        family="memo",
        definition={"type": "function", "function": {"name": name}},
        budget="write_proposals",
        propose=propose,
        allows_always=allows_always,
    )


class RegistryTests(unittest.TestCase):
    def test_parse_tool_arguments_accepts_dict_and_json_string(self):
        self.assertEqual(parse_tool_arguments({"a": 1}), {"a": 1})
        self.assertEqual(parse_tool_arguments('{"a": 1}'), {"a": 1})
        self.assertEqual(parse_tool_arguments(None), {})

    def test_parse_tool_arguments_rejects_non_object_payloads(self):
        for bad in ("not json", "[1, 2]", "42"):
            with self.subTest(bad=bad):
                with self.assertRaises(WorkspaceToolArgumentError):
                    parse_tool_arguments(bad)

    def test_validation_problems_reports_field_locations(self):
        try:
            MemoCreateArguments.model_validate({"content": ""})
        except ValidationError as exc:
            problems = validation_problems(exc)
        else:
            self.fail("expected a validation error")
        self.assertTrue(any("content" in problem for problem in problems))

    def test_toolbox_definitions_and_budget_routing(self):
        toolbox = ChatWorkspaceToolbox(MEMO_TOOL_SPECS, user_id=1, chat_room_id="room-1")
        names = {definition["function"]["name"] for definition in toolbox.definitions()}
        self.assertEqual(
            names,
            {
                MEMO_LIST_TOOL_NAME,
                MEMO_SEARCH_TOOL_NAME,
                MEMO_READ_TOOL_NAME,
                MEMO_CREATE_TOOL_NAME,
                MEMO_APPEND_TOOL_NAME,
                MEMO_EDIT_TOOL_NAME,
            },
        )
        self.assertTrue(toolbox.handles(MEMO_CREATE_TOOL_NAME))
        self.assertFalse(toolbox.handles("unrelated_tool"))
        self.assertTrue(toolbox.is_write(MEMO_CREATE_TOOL_NAME))
        self.assertFalse(toolbox.is_write(MEMO_LIST_TOOL_NAME))
        self.assertTrue(toolbox.uses_read_budget(MEMO_READ_TOOL_NAME))
        self.assertFalse(toolbox.uses_read_budget(MEMO_LIST_TOOL_NAME))

    def test_build_workspace_toolbox_off_when_skill_disabled(self):
        self.assertIsNone(
            build_workspace_toolbox(
                user_id=1, chat_room_id="room-1", memo_tools_enabled=False, external_input_in_turn=False
            )
        )

    def test_build_workspace_toolbox_carries_external_input_flag(self):
        toolbox = build_workspace_toolbox(
            user_id=1, chat_room_id="room-1", memo_tools_enabled=True, external_input_in_turn=True
        )
        self.assertIsNotNone(toolbox)
        self.assertTrue(toolbox.external_input_in_turn)
        self.assertIs(get_workspace_tool_spec(MEMO_CREATE_TOOL_NAME).execute is not None, True)
        self.assertIsNone(get_workspace_tool_spec("does_not_exist"))


class MemoArgumentValidationTests(unittest.TestCase):
    def test_memo_create_requires_nonblank_content(self):
        with self.assertRaises(ValidationError):
            MemoCreateArguments.model_validate({"content": "   "})

    def test_memo_append_requires_nonblank_text(self):
        with self.assertRaises(ValidationError):
            MemoAppendArguments.model_validate({"memo_id": 1, "text": "  "})

    def test_memo_edit_rejects_neither_edits_nor_content(self):
        with self.assertRaises(ValidationError):
            MemoEditArguments.model_validate({"memo_id": 1})

    def test_memo_edit_rejects_both_edits_and_content(self):
        with self.assertRaises(ValidationError):
            MemoEditArguments.model_validate(
                {"memo_id": 1, "edits": [{"old_string": "a", "new_string": "b"}], "content": "whole body"}
            )

    def test_memo_edit_accepts_edits_only(self):
        parsed = MemoEditArguments.model_validate(
            {"memo_id": 1, "edits": [{"old_string": "a", "new_string": "b"}]}
        )
        self.assertEqual(len(parsed.edits), 1)
        self.assertIsNone(parsed.content)


class MemoProposeHandlerTests(unittest.TestCase):
    def _memo(self, **overrides) -> McpMemoDetail:
        defaults = {
            "id": 42,
            "title": "対象メモ",
            "revision": 1,
            "is_shared": False,
            "content": "今日は晴れです。明日は雨です。",
        }
        defaults.update(overrides)
        return McpMemoDetail(**defaults)

    def test_propose_memo_create_builds_a_preview_with_a_derived_title(self):
        proposal = asyncio.run(_propose_memo_create(1, {"content": "買い物リスト\n- 牛乳", "title": ""}))
        self.assertEqual(proposal.preview["kind"], MEMO_CREATE_TOOL_NAME)
        self.assertEqual(proposal.preview["title"], proposal.target_title)
        self.assertIn("牛乳", proposal.preview["content"])
        self.assertFalse(proposal.shared)

    def test_propose_memo_append_rejects_when_result_exceeds_max_length(self):
        long_memo = self._memo(content="x" * (MAX_MEMO_STORED_CONTENT_LENGTH - 10))
        with patch("services.chat_workspace_tools.memo.get_memo", AsyncMock(return_value=long_memo)):
            with self.assertRaises(WorkspaceToolError) as ctx:
                asyncio.run(_propose_memo_append(1, {"memo_id": 42, "text": "y" * 50}))
        self.assertEqual(ctx.exception.code, "content_too_long")

    def test_propose_memo_append_builds_preview_and_target_ref(self):
        memo = self._memo()
        with patch("services.chat_workspace_tools.memo.get_memo", AsyncMock(return_value=memo)):
            proposal = asyncio.run(_propose_memo_append(1, {"memo_id": 42, "text": "追記します。"}))
        self.assertEqual(proposal.preview["kind"], MEMO_APPEND_TOOL_NAME)
        self.assertEqual(proposal.target_ref, {"memo_id": 42, "base_revision": 1, "shared": False})
        self.assertEqual(proposal.target_title, "対象メモ")

    def test_propose_memo_edit_uses_the_shared_fixture_cases(self):
        cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]
        for case in cases:
            expected = case["expected"]
            body = _expand_repeats(case["body"])
            edits = [
                {"old_string": _expand_repeats(edit["old_string"]), "new_string": _expand_repeats(edit["new_string"])}
                for edit in case["edits"]
            ]
            memo = self._memo(content=body)
            with self.subTest(name=case["name"]):
                with patch("services.chat_workspace_tools.memo.get_memo", AsyncMock(return_value=memo)):
                    if "failure" in expected:
                        with self.assertRaises(WorkspaceToolArgumentError):
                            asyncio.run(_propose_memo_edit(1, {"memo_id": 42, "edits": edits}))
                    else:
                        proposal = asyncio.run(_propose_memo_edit(1, {"memo_id": 42, "edits": edits}))
                        self.assertEqual(proposal.preview["mode"], "edits")
                        self.assertEqual(len(proposal.preview["edits"]), len(edits))

    def test_propose_memo_edit_content_mode_builds_whole_body_preview(self):
        memo = self._memo()
        with patch("services.chat_workspace_tools.memo.get_memo", AsyncMock(return_value=memo)):
            proposal = asyncio.run(_propose_memo_edit(1, {"memo_id": 42, "content": "全文書き換え"}))
        self.assertEqual(proposal.preview["mode"], "content")
        self.assertEqual(proposal.preview["content"], "全文書き換え")


def _expand_repeats(value):
    if isinstance(value, dict) and "repeat" in value:
        return str(value["repeat"]) * int(value["times"])
    return value


class WorkspaceToolRunnerTests(unittest.TestCase):
    def _runner(self, spec: ToolSpec | list[ToolSpec]) -> tuple[WorkspaceToolRunner, list]:
        specs = spec if isinstance(spec, list) else [spec]
        toolbox = ChatWorkspaceToolbox(specs, user_id=7, chat_room_id="room-7")
        published: list[tuple[str, dict]] = []
        runner = WorkspaceToolRunner(toolbox, publish=lambda event, payload: published.append((event, payload)))
        return runner, published

    # Dispatch -----------------------------------------------------------------

    def test_run_dispatches_reads_to_read_and_writes_to_propose(self):
        read_spec = _fake_read_spec()
        runner, _ = self._runner(read_spec)
        state = _make_state()
        result = runner.run(state, _tool_call("fake_read", q="hi"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(state.telemetry.workspace_read_calls, 1)
        self.assertEqual(state.telemetry.workspace_write_proposals, 0)

        write_spec = _fake_write_spec(allows_always=False)
        with patch(
            "services.chat_workspace_tools.runner.create_pending_approval",
            AsyncMock(return_value={"id": "a1", "status": "pending", "tool": "fake_write"}),
        ):
            runner, _ = self._runner(write_spec)
            state = _make_state()
            result = runner.run(state, _tool_call("fake_write", text="x"))
        self.assertEqual(result["status"], "awaiting_user_approval")
        self.assertEqual(state.telemetry.workspace_write_proposals, 1)
        self.assertEqual(state.telemetry.workspace_read_calls, 0)

    # Reads ----------------------------------------------------------------------

    def test_read_registers_evidence_and_records_the_search(self):
        spec = _fake_read_spec()
        runner, published = self._runner(spec)
        state = _make_state()
        result = runner.run(state, _tool_call("fake_read", q="hi"))
        self.assertEqual(result["status"], "ok")
        state.evidence_store.add_reference_payload.assert_called_once()
        _, kwargs = state.evidence_store.add_reference_payload.call_args
        self.assertEqual(kwargs["source_type"], "memo")
        state.turn_state.record_search.assert_called_once()
        self.assertEqual(state.turn_state.record_search.call_args.kwargs["status"], "ok")
        self.assertEqual([event for event, _ in published], ["workspace_tool_started", "workspace_tool_completed"])

    def test_read_reports_step_limit_when_the_read_budget_is_exhausted(self):
        spec = _fake_read_spec()
        runner, published = self._runner(spec)
        budget = AgentStepBudget(max_llm_turns=8, max_tool_calls=6, max_read_calls=1, read_calls=1)
        state = _make_state(budget=budget)
        result = runner.run(state, _tool_call("fake_read", q="hi"))
        self.assertEqual(result["status"], "step_limit_reached")
        self.assertEqual(state.telemetry.workspace_read_calls, 0)
        self.assertEqual(published, [])

    def test_read_reports_invalid_arguments_and_counts_telemetry(self):
        async def read(user_id, arguments, max_chars):  # pragma: no cover - never reached
            raise AssertionError("should not run when arguments are invalid")

        spec = ToolSpec(
            name="fake_read",
            family="memo",
            definition={"type": "function", "function": {"name": "fake_read"}},
            budget="reads",
            read=read,
        )
        runner, _ = self._runner(spec)
        state = _make_state()
        with patch(
            "services.chat_workspace_tools.runner.parse_tool_arguments",
            side_effect=WorkspaceToolArgumentError(("bad",)),
        ):
            result = runner.run(state, _tool_call("fake_read"))
        self.assertEqual(result["status"], "invalid_arguments")
        self.assertEqual(state.telemetry.workspace_invalid_arguments, 1)

    # Write proposals --------------------------------------------------------------

    def test_propose_creates_a_pending_card_and_a_server_summary(self):
        spec = _fake_write_spec(allows_always=False)
        runner, published = self._runner(spec)
        state = _make_state()
        with patch(
            "services.chat_workspace_tools.runner.create_pending_approval",
            AsyncMock(return_value={"id": "abc", "status": "pending", "tool": "fake_write"}),
        ) as create:
            result = runner.run(state, _tool_call("fake_write", text="hello"))
        create.assert_awaited_once()
        self.assertEqual(result, {
            "status": "awaiting_user_approval",
            "approval_id": "abc",
            "message": AWAITING_APPROVAL_MESSAGE,
        })
        self.assertEqual(state.tool_approval_parts, [{"id": "abc", "status": "pending", "tool": "fake_write"}])
        self.assertEqual(len(state.approval_pending_summaries), 1)
        summary = json.loads(state.approval_pending_summaries[0])
        self.assertEqual(summary, {"tool": "fake_write", "target": "Target"})
        self.assertEqual([event for event, _ in published], ["workspace_tool_started", "tool_approval_prepared"])

    def test_memo_append_and_edit_require_reading_the_same_target_first(self):
        read = _fake_read_spec(name=MEMO_READ_TOOL_NAME, memo_ids=(42,))
        append = _fake_write_spec(allows_always=False, name=MEMO_APPEND_TOOL_NAME)
        edit = _fake_write_spec(allows_always=False, name=MEMO_EDIT_TOOL_NAME)
        runner, published = self._runner([read, append, edit])
        state = _make_state()

        result = runner.run(state, _tool_call(MEMO_APPEND_TOOL_NAME, memo_id=42, text="new"))
        self.assertEqual(result, {
            "status": "read_required",
            "message": "Read the target memo with memo_read before proposing an append or edit.",
        })

        # 拒否は提案ではないので、提案の予算と件数を使わない。
        # A refusal is not a proposal, so it spends neither the proposal budget nor the count.
        self.assertEqual(state.budget.write_proposals, 0)
        self.assertEqual(state.telemetry.workspace_write_proposals, 0)

        runner.run(state, _tool_call(MEMO_READ_TOOL_NAME, memo_id=42))
        result = runner.run(state, _tool_call(MEMO_EDIT_TOOL_NAME, memo_id=43, edits=[]))
        self.assertEqual(result["status"], "read_required")
        self.assertEqual(state.telemetry.workspace_write_proposals, 0)

        with patch(
            "services.chat_workspace_tools.runner.create_pending_approval",
            AsyncMock(return_value={"id": "a1", "status": "pending", "tool": MEMO_APPEND_TOOL_NAME}),
        ) as create:
            result = runner.run(state, _tool_call(MEMO_APPEND_TOOL_NAME, memo_id=42, text="new"))

        create.assert_awaited_once()
        self.assertEqual(result["status"], "awaiting_user_approval")
        self.assertEqual(
            [event for event, _ in published],
            [
                "workspace_tool_started",
                "workspace_tool_completed",
                "workspace_tool_started",
                "workspace_tool_completed",
                "workspace_tool_started",
                "workspace_tool_completed",
                "workspace_tool_started",
                "tool_approval_prepared",
            ],
        )
        self.assertEqual(state.telemetry.workspace_write_proposals, 1)

    def test_propose_reports_step_limit_when_the_write_budget_is_exhausted(self):
        spec = _fake_write_spec()
        runner, published = self._runner(spec)
        budget = AgentStepBudget(max_llm_turns=8, max_tool_calls=6, max_write_proposals=1, write_proposals=1)
        state = _make_state(budget=budget)
        with patch("services.chat_workspace_tools.runner.create_pending_approval") as create:
            result = runner.run(state, _tool_call("fake_write", text="x"))
        create.assert_not_called()
        self.assertEqual(result["status"], "step_limit_reached")
        self.assertEqual(state.telemetry.workspace_write_proposals, 0)
        self.assertEqual(published, [])

    def test_propose_turns_a_proposal_failure_into_an_error_payload(self):
        spec = _fake_write_spec(raise_error=WorkspaceToolError("target_not_found"))
        runner, _ = self._runner(spec)
        state = _make_state()
        result = runner.run(state, _tool_call("fake_write", text="x"))
        self.assertEqual(result["error_code"], "target_not_found")
        self.assertIn("memo_id", result["message"])
        state.turn_state.record_search.assert_called_once()
        self.assertEqual(state.turn_state.record_search.call_args.kwargs["status"], "target_not_found")

    # Auto approval ------------------------------------------------------------------

    def test_auto_approval_runs_the_write_immediately_when_granted(self):
        spec = _fake_write_spec(allows_always=True, shared=False)
        runner, published = self._runner(spec)
        state = _make_state()
        with (
            patch("services.chat_workspace_tools.runner.has_auto_approval", AsyncMock(return_value=True)),
            patch("services.chat_workspace_tools.runner.consume_chat_tool_write_limit", return_value=(True, 0)),
            patch(
                "services.chat_workspace_tools.runner.execute_auto_approved",
                AsyncMock(
                    return_value={
                        "id": "auto-1",
                        "status": "succeeded",
                        "tool": "fake_write",
                        "result": {"target_id": 9, "target_title": "Target"},
                    }
                ),
            ) as execute,
            patch("services.chat_workspace_tools.runner.create_pending_approval") as create,
        ):
            result = runner.run(state, _tool_call("fake_write", text="x"))
        execute.assert_awaited_once()
        create.assert_not_called()
        self.assertEqual(result, {"status": "executed", "result": {"target_id": 9, "target_title": "Target"}})
        self.assertEqual(state.telemetry.workspace_auto_executions, 1)
        self.assertEqual(
            [event for event, _ in published], ["workspace_tool_started", "workspace_tool_completed"]
        )

    def test_auto_approval_is_never_offered_for_a_shared_target(self):
        spec = _fake_write_spec(allows_always=True, shared=True)
        runner, _ = self._runner(spec)
        state = _make_state()
        with (
            patch("services.chat_workspace_tools.runner.has_auto_approval", AsyncMock(return_value=True)) as grant,
            patch(
                "services.chat_workspace_tools.runner.create_pending_approval",
                AsyncMock(return_value={"id": "abc", "status": "pending", "tool": "fake_write"}),
            ) as create,
        ):
            runner.run(state, _tool_call("fake_write", text="x"))
        grant.assert_not_called()
        create.assert_awaited_once()

    def test_auto_approval_is_suppressed_after_the_turn_read_external_content(self):
        spec = _fake_write_spec(allows_always=True, shared=False)
        runner, _ = self._runner(spec)
        state = _make_state(untrusted_input_ingested=True)
        with (
            patch("services.chat_workspace_tools.runner.has_auto_approval", AsyncMock(return_value=True)),
            patch(
                "services.chat_workspace_tools.runner.create_pending_approval",
                AsyncMock(return_value={"id": "abc", "status": "pending", "tool": "fake_write"}),
            ) as create,
            patch("services.chat_workspace_tools.runner.execute_auto_approved") as execute,
        ):
            result = runner.run(state, _tool_call("fake_write", text="x"))
        execute.assert_not_called()
        create.assert_awaited_once()
        self.assertEqual(result["status"], "awaiting_user_approval")
        self.assertTrue(state.telemetry.auto_approval_suppressed_by_untrusted_input)

    def test_auto_approval_falls_back_to_a_pending_card_when_the_write_limit_is_hit(self):
        spec = _fake_write_spec(allows_always=True, shared=False)
        runner, _ = self._runner(spec)
        state = _make_state()
        with (
            patch("services.chat_workspace_tools.runner.has_auto_approval", AsyncMock(return_value=True)),
            patch("services.chat_workspace_tools.runner.consume_chat_tool_write_limit", return_value=(False, 30)),
            patch(
                "services.chat_workspace_tools.runner.create_pending_approval",
                AsyncMock(return_value={"id": "abc", "status": "pending", "tool": "fake_write"}),
            ) as create,
            patch("services.chat_workspace_tools.runner.execute_auto_approved") as execute,
        ):
            runner.run(state, _tool_call("fake_write", text="x"))
        execute.assert_not_called()
        create.assert_awaited_once()

    # Interruption -------------------------------------------------------------------

    def test_settle_after_interruption_cancels_only_pending_cards(self):
        spec = _fake_write_spec()
        runner, _ = self._runner(spec)
        cards = [
            {"id": "p1", "status": "pending"},
            {"id": "p2", "status": "pending"},
            {"id": "s1", "status": "succeeded"},
        ]
        with patch(
            "services.chat_workspace_tools.runner.cancel_unattached_approvals", AsyncMock(return_value=2)
        ) as cancel:
            settled = runner.settle_after_interruption(cards)
        cancel.assert_awaited_once()
        (cancelled_ids, _user_id), _ = cancel.call_args
        self.assertEqual(set(cancelled_ids), {"p1", "p2"})
        statuses = {card["id"]: card["status"] for card in settled}
        self.assertEqual(statuses, {"p1": "cancelled", "p2": "cancelled", "s1": "succeeded"})

    def test_settle_after_interruption_is_a_noop_without_pending_cards(self):
        spec = _fake_write_spec()
        runner, _ = self._runner(spec)
        cards = [{"id": "s1", "status": "succeeded"}]
        with patch("services.chat_workspace_tools.runner.cancel_unattached_approvals") as cancel:
            settled = runner.settle_after_interruption(cards)
        cancel.assert_not_called()
        self.assertEqual(settled, cards)


class ChatGenerationApprovalPendingTests(unittest.TestCase):
    """1ターンの生成ループが、承認待ちのカードをどう締めるかを検証する（ADR 0009 の単一ループを保つ）。

    Verifies how the single-turn generation loop (services/chat_generation.py) closes once a
    write proposal is left for approval: no new ending phase (ADR 0009), the next decision gets
    no tools at all, and the budget-exhaustion telemetry is not tripped for this reason.
    """

    def _make_job(self, workspace_tools, persist_response):
        return ChatGenerationJob(
            conversation_messages=[{"role": "user", "content": "メモに書いて"}],
            model="openai/gpt-oss-120b",
            persist_response=persist_response,
            on_error=MagicMock(),
            workspace_tools=workspace_tools,
        )

    def _run(self, job, stream):
        with (
            patch.dict("services.chat_generation.os.environ", {"LLM_STREAM_MAX_RETRIES": "0"}, clear=False),
            patch("services.chat_generation.is_web_search_enabled", return_value=False),
            patch("services.chat_generation.get_llm_response_stream", side_effect=stream),
            patch("services.chat_generation.choose_web_search_images", return_value=[]),
        ):
            job._run()

    def test_a_pending_write_proposal_closes_the_turn_with_a_tool_free_answer(self):
        toolbox = ChatWorkspaceToolbox([_fake_write_spec(allows_always=False)], user_id=1, chat_room_id="room-1")
        offered_tools = []

        def stream(_messages, _model, *, tools=None, **_kwargs):
            offered_tools.append(bool(tools))
            if len(offered_tools) == 1:
                yield json.dumps([_tool_call("fake_write", text="hello")])
                return
            yield "承認をお待ちください。"

        persisted = []

        def persist_response(response, *, message_parts=None, web_search_context=None, tool_approval_ids=None):
            persisted.append({"response": response, "message_parts": message_parts, "ids": tool_approval_ids})

        job = self._make_job(toolbox, persist_response)
        with patch(
            "services.chat_workspace_tools.runner.create_pending_approval",
            AsyncMock(return_value={"id": "abc", "status": "pending", "tool": "fake_write"}),
        ):
            self._run(job, stream)

        # 1回目はツールを提示し、承認待ちが残った2回目は一つも提示しない。
        # The first decision offers the tool; the second, with a card pending, offers none.
        self.assertEqual(offered_tools, [True, False])
        self.assertTrue(job._telemetry.approval_pending_turn)
        self.assertFalse(job._telemetry.tools_withdrawn_by_budget)

        self.assertEqual(len(persisted), 1)
        saved = persisted[0]
        self.assertEqual(saved["ids"], ["abc"])
        approval_parts = [
            part for part in (saved["message_parts"] or []) if part.get("type") == TOOL_APPROVAL_PART_TYPE
        ]
        self.assertEqual(len(approval_parts), 1)
        self.assertEqual(approval_parts[0]["approval"]["id"], "abc")


if __name__ == "__main__":
    unittest.main()
