"""モデルへ提示するツールの決定と、要求されたツール呼び出しの実行フェーズ。

The phase that decides which tools the model is offered and runs the tool calls it requests.

検索系（メモ/マイコンテキスト、公開プロンプト）と読み取り系（根拠の再読み取り、
ページ本文）はここで実行する。Web 検索は `_run_web_search_tool_call`
（`chat_generation_web_search`）へ渡す。
Lookups (memo / My Context, public prompts) and reads (re-reading evidence, page bodies) run
here; web search is handed to `_run_web_search_tool_call` (`chat_generation_web_search`).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Callable
from typing import Any

from .chat_agent_budget import AgentStepBudget
from .chat_evidence_store import (
    GET_EVIDENCE_TOOL_NAME,
    EvidenceStore,
    get_evidence_tool_definition,
)
from .chat_generation_job_base import ChatGenerationJobBase
from .chat_generation_turn import ChatTurnRunState
from .chat_tool_calls import (
    _EXTERNAL_CONTENT_TOOL_NAMES,
    _contains_unconfirmed_context_facts,
    _includes_external_evidence,
    _is_memo_only_request,
    _normalize_tool_call,
    _tool_argument_text,
    _tool_result_message,
)
from .chat_web_page_reader import (
    READ_WEB_PAGE_TOOL_NAME,
    read_web_page_tool_definition,
)
from .personal_knowledge import (
    PERSONAL_KNOWLEDGE_TOOL_NAME,
    get_personal_knowledge_tool_definition,
)
from .research_state import TurnState
from .selected_reference_context import (
    PERSONAL_KNOWLEDGE_SOURCE,
    SHARED_PROMPT_SOURCE,
)
from .shared_prompt_lookup import (
    SHARED_PROMPT_TOOL_NAME,
    get_shared_prompt_tool_definition,
)
from .web_search import (
    get_web_search_tool_definition,
    is_web_search_enabled,
)
from .web_search_trace import (
    TraceStep,
    selected_reference_step,
)

logger = logging.getLogger(__name__)


# ツールの提示判定と実行の振り分けを担う Mixin
# Mixin that decides the offered tools and routes tool calls to their runners
class ChatGenerationToolsMixin(ChatGenerationJobBase):
    # 検索系ツールの結果を回答トレースの1ステップへ変換する。参照元はイベント種別から決まる。
    # Turn a lookup tool result into one answer-trace step; the source follows the event prefix.
    @staticmethod
    def _lookup_trace_step(
        event_prefix: str,
        payload: dict[str, Any],
        query: str,
    ) -> TraceStep:
        return selected_reference_step(
            (
                PERSONAL_KNOWLEDGE_SOURCE
                if event_prefix == "personal_knowledge_search"
                else SHARED_PROMPT_SOURCE
            ),
            payload,
            query=query,
        )

    # 検索系ツール呼び出しの受け付け判定フェーズ。実行できない場合は結果を積んで None を返す。
    # The admission phase for a lookup tool call; on refusal it appends the tool result
    # and returns None instead of a step and query.
    def _begin_lookup_tool_call(
        self,
        tool_call: dict[str, Any],
        *,
        tool_name: str,
        search: Callable[[str], dict[str, Any]] | None,
        event_prefix: str,
        current_messages: list[dict[str, Any]],
        budget: AgentStepBudget,
        turn_state: TurnState,
    ) -> tuple[int, str] | None:
        if budget.tool_calls_exhausted:
            current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "step_limit_reached",
                        "message": "The search limit has been reached.",
                    },
                )
            )
            return None

        step = budget.start_tool_call()
        self._telemetry.tool_calls = budget.tool_calls
        self._telemetry.lookup_call_count += 1

        if search is None:
            turn_state.record_search(tool_name=tool_name, status="unsupported_tool")
            current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "unsupported_tool",
                        "message": f"Unsupported tool: {tool_name}",
                    },
                )
            )
            return None

        args_raw = tool_call.get("function", {}).get("arguments", "{}")
        try:
            args = json.loads(args_raw)
        except Exception:
            # 日本語: モデルが渡したツール引数が JSON として壊れていた場合は空引数として扱います。
            # English: Treat tool arguments the model produced as empty when they are not valid JSON.
            logger.debug("Discarded malformed tool-call arguments from the model.", exc_info=True)
            args = {}
        if not isinstance(args, dict):
            args = {}

        query = _tool_argument_text(args.get("query"))
        if not query:
            turn_state.record_search(tool_name=tool_name, status="invalid_arguments")
            current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "invalid_arguments",
                        "message": "Search query is empty.",
                    },
                )
            )
            return None
        self._publish(
            f"{event_prefix}_started",
            {"query": query, "step": step, "max_steps": budget.max_steps},
        )
        return step, query

    # 検索系ツールの呼び出しを1件実行する。ステップ会計は共有の予算オブジェクトが持つ。
    # メモ検索と共有プロンプト検索は進行管理が同じなので、1つの実行部を共有する。
    # Execute one lookup tool call. Step accounting lives in the shared budget object. The
    # memo and shared prompt tools share this runner because their handling is identical.
    def _run_lookup_tool_call(
        self,
        tool_call: dict[str, Any],
        *,
        tool_name: str,
        search: Callable[[str], dict[str, Any]] | None,
        event_prefix: str,
        result_counts: tuple[str, ...],
        failure_log_message: str,
        failure_tool_message: str,
        current_messages: list[dict[str, Any]],
        budget: AgentStepBudget,
        turn_state: TurnState,
        evidence_store: EvidenceStore,
        trace_steps: list[TraceStep] | None = None,
    ) -> dict[str, Any] | None:
        admitted = self._begin_lookup_tool_call(
            tool_call,
            tool_name=tool_name,
            search=search,
            event_prefix=event_prefix,
            current_messages=current_messages,
            budget=budget,
            turn_state=turn_state,
        )
        if admitted is None:
            return None
        step, query = admitted
        # 受け付け判定を通った時点で search は None ではない。
        # Admission guarantees a callable search here.
        try:
            payload = search(query)  # type: ignore[misc]
            if inspect.isawaitable(payload):
                # The generation loop is intentionally a synchronous worker because the LLM
                # stream is blocking. Native-async repository callbacks are bridged only at
                # this worker boundary; request-path database access never uses run_blocking.
                payload = asyncio.run(payload)  # type: ignore[arg-type]
            if not isinstance(payload, dict):
                raise TypeError("selected reference lookup returned a non-object payload")
        except Exception:
            logger.exception(failure_log_message)
            self._publish(
                f"{event_prefix}_failed",
                {"query": query, "step": step, "max_steps": budget.max_steps},
            )
            current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "failed",
                        "message": failure_tool_message,
                    },
                )
            )
            turn_state.record_search(
                tool_name=tool_name,
                query=query,
                status="failed",
            )
            if trace_steps is not None:
                trace_steps.append(
                    self._lookup_trace_step(event_prefix, {"status": "failed"}, query)
                )
            return None

        # 参照元が「検索できなかった」と返した場合も障害として扱う。0件として通すと、
        # UI もモデルも「該当なし」と伝えてしまう。
        # A source reporting that it could not search is a failure too. Passing it through as a
        # zero-hit result would make both the UI and the model claim that nothing matched.
        status = str(payload.get("status") or "")
        evidence_refs = evidence_store.add_reference_payload(
            payload,
            source_type=event_prefix,
            query=query,
        )
        turn_state.record_search(
            tool_name=tool_name,
            query=query,
            evidence_refs=evidence_refs,
            status=status or "ok",
        )
        if status == "failed":
            logger.warning("%s (status=failed)", failure_log_message)
            self._publish(
                f"{event_prefix}_failed",
                {"query": query, "step": step, "max_steps": budget.max_steps},
            )
            current_messages.append(_tool_result_message(tool_call, payload))
            if trace_steps is not None:
                trace_steps.append(self._lookup_trace_step(event_prefix, payload, query))
            return payload

        self._publish(
            f"{event_prefix}_completed",
            {
                "query": query,
                "status": status,
                **{key: int(payload.get(key) or 0) for key in result_counts},
                "step": step,
                "max_steps": budget.max_steps,
            },
        )
        current_messages.append(_tool_result_message(tool_call, payload))
        if trace_steps is not None and status != "already_searched":
            trace_steps.append(self._lookup_trace_step(event_prefix, payload, query))
        return payload

    # モデルへ提示するツール定義を決めるフェーズ。
    # The phase that decides which tool definitions the model is offered.
    def _configure_agent_tools(self, state: ChatTurnRunState) -> None:
        suppress_external_lookup_tools = (
            self._workspace_tools is not None
            and _is_memo_only_request(state.latest_user_message)
        )
        web_search_tool = get_web_search_tool_definition()
        personal_knowledge_tool = (
            get_personal_knowledge_tool_definition()
            if self._personal_knowledge_search is not None
            else None
        )
        shared_prompt_tool = (
            get_shared_prompt_tool_definition()
            if self._shared_prompt_search is not None
            else None
        )

        # メモ検索はWeb検索の設定に依存しないので、どちらか一方だけでもツールを渡す。
        # Memo lookup does not depend on the web search settings, so either tool alone
        # is still offered to the model.
        configured_tools: list[dict[str, Any]] = []
        if is_web_search_enabled() and not suppress_external_lookup_tools:
            configured_tools.append(web_search_tool)
        if personal_knowledge_tool is not None:
            configured_tools.append(personal_knowledge_tool)
        if shared_prompt_tool is not None:
            configured_tools.append(shared_prompt_tool)
        # 利用者のデータを読み書きするツールは、検索系の後・読み直しツールの前に固定の順で並べる。
        # ターンの途中で一覧を変えない（ADR 0011）。
        # The tools for the user's own data go after the searches and before the re-read tools,
        # in a fixed order that does not change mid-turn (ADR 0011).
        if self._workspace_tools is not None:
            configured_tools.extend(self._workspace_tools.definitions())
        if not suppress_external_lookup_tools:
            configured_tools.append(get_evidence_tool_definition())
            configured_tools.append(read_web_page_tool_definition())
        state.configured_tools = configured_tools
        state.telemetry.research_phase_used = bool(self._selected_reference_trace)

    # モデルが要求したツール呼び出しを種類別の実行部へ振り分けるフェーズ。
    # The phase that routes the model's requested tool calls to their per-tool runners.
    def _dispatch_tool_calls(
        self,
        state: ChatTurnRunState,
        tool_calls_buffer: list[dict[str, Any]],
        llm_step: int,
    ) -> None:
        normalized_tool_calls = [
            _normalize_tool_call(tool_call, step=llm_step, index=index)
            for index, tool_call in enumerate(tool_calls_buffer, start=1)
        ]
        assistant_tool_call_msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": normalized_tool_calls,
        }
        state.current_messages = [assistant_tool_call_msg]

        for tc in normalized_tool_calls:
            # ツールごとの実行と結果の追加
            # Execute each tool and append results
            func_name = tc.get("function", {}).get("name")
            available_names = {
                tool["function"]["name"] for tool in self._available_agent_tools(state)
            }
            if func_name not in available_names:
                self._record_unsupported_tool_call(state, tc, func_name)
                continue
            if func_name in _EXTERNAL_CONTENT_TOOL_NAMES:
                # 外部の内容を読むツール。以後この回答の書き込みは「常に承認」でも自動では実行しない。
                # A tool that reads external content; from here on no write in this reply runs
                # on its own, even under "always approve".
                state.untrusted_input_ingested = True
            if self._workspace_tool_runner is not None and self._workspace_tools is not None and (
                self._workspace_tools.handles(func_name)
            ):
                state.current_messages.append(
                    _tool_result_message(tc, self._workspace_tool_runner.run(state, tc))
                )
                continue
            if (
                func_name == PERSONAL_KNOWLEDGE_TOOL_NAME
                and self._personal_knowledge_search is not None
            ):
                lookup_payload = self._run_lookup_tool_call(
                    tc,
                    tool_name=PERSONAL_KNOWLEDGE_TOOL_NAME,
                    search=self._personal_knowledge_search,
                    event_prefix="personal_knowledge_search",
                    result_counts=("memo_count", "context_fact_count"),
                    failure_log_message="Memo / context search via tool call failed.",
                    failure_tool_message="Memo and My Context search failed.",
                    current_messages=state.current_messages,
                    budget=state.budget,
                    turn_state=state.turn_state,
                    evidence_store=state.evidence_store,
                    trace_steps=state.web_search_trace_steps,
                )
                if _contains_unconfirmed_context_facts(lookup_payload):
                    # MCP/import facts can be active without owner review. Treat them like
                    # external input so "always approve" cannot turn one into a silent write.
                    state.untrusted_input_ingested = True
                continue

            if (
                func_name == SHARED_PROMPT_TOOL_NAME
                and self._shared_prompt_search is not None
            ):
                self._run_lookup_tool_call(
                    tc,
                    tool_name=SHARED_PROMPT_TOOL_NAME,
                    search=self._shared_prompt_search,
                    event_prefix="shared_prompt_search",
                    result_counts=("prompt_count",),
                    failure_log_message="Shared prompt search via tool call failed.",
                    failure_tool_message="Shared prompt search failed.",
                    current_messages=state.current_messages,
                    budget=state.budget,
                    turn_state=state.turn_state,
                    evidence_store=state.evidence_store,
                    trace_steps=state.web_search_trace_steps,
                )
                continue

            if func_name in (GET_EVIDENCE_TOOL_NAME, READ_WEB_PAGE_TOOL_NAME):
                self._run_read_tool_call(state, tc)
                continue

            if func_name != "web_search":
                self._record_unsupported_tool_call(state, tc, func_name)
                continue

            self._run_web_search_tool_call(state, tc)

        # 同じ判断の中の提案はまとめて受け付け、承認待ちが残ったら次の判断をツールなしの回答にする。
        # Proposals within one decision are all accepted; if any awaits approval, the next
        # decision is a tool-free answer.
        if state.approval_pending_summaries and not state.approval_pending:
            state.approval_pending = True
            state.telemetry.approval_pending_turn = True

    # 次のモデル判断へ実際に提示するツール。実行可否（_available_agent_tools）とは
    # 別の判断で、こちらは「この判断でまだ調査を続けてよいか」を決める。
    # The tools actually offered to the next model decision. Kept apart from what may still be
    # executed (_available_agent_tools): this one decides whether research may continue at all.
    def _offered_agent_tools(self, state: ChatTurnRunState) -> list[dict[str, Any]]:
        # 障害からの縮退中はツールを1つも出さない。取り下げの理由は予算ではないため、
        # 呼び出し側が予算枯渇のテレメトリと取り違えないようにしている。
        # Offer no tool at all while degrading after a failure. The caller keeps this apart
        # from the budget-exhaustion telemetry because the reason is not the budget.
        if state.tools_disabled_after_failure:
            return []
        # 書き込みの提案が承認待ちなら、ツールを外した回答で締める。新しい終了条件は作らず、
        # 次の判断が force_answer になる（ADR 0009）。
        # A write proposal awaiting approval closes the turn with a tool-free answer: no new
        # ending condition, the next decision is simply force_answer (ADR 0009).
        if state.approval_pending:
            return []
        # 最後のモデル判断は必ずツールなしの回答へ予約する。ここを空にすると
        # force_answer が立ち、次の1回が本文を書くステップになる。
        # Reserve the last model decision for a tool-free answer: returning nothing here
        # raises force_answer, so the next call is the step that writes the body.
        if state.budget.llm_turns >= state.budget.max_llm_turns - 1:
            return []
        return self._available_agent_tools(state)

    @staticmethod
    def _available_agent_tools(state: ChatTurnRunState) -> list[dict[str, Any]]:
        """Withdraw exhausted search/read tools independently.

        根拠を増やせるツール（検索系）があるターンでは、読み取りツールを根拠が届く前から
        提示する。ツール定義はプロンプトの先頭に置かれるため、根拠が届いた時点で一覧が
        変わると、それ以降のステップのプロンプトキャッシュがすべて外れる。根拠が無いうちの
        呼び出しは not_found を返す。検索系ツールが無いターンは根拠がターン中に増えない
        ので、一覧は元から変わらず、根拠が無ければ読み取りツールも出さない。
        When the turn has a tool that can add evidence (a search), read tools are offered
        before any evidence arrives. Tool definitions sit at the very start of the prompt, so
        changing the list once evidence appears would evict the prompt cache for every later
        step; an early call simply returns not_found. Without a search tool the evidence cannot
        grow during the turn, so the list is stable anyway and read tools stay hidden until
        there is something to read.
        """
        read_tool_names = {GET_EVIDENCE_TOOL_NAME, READ_WEB_PAGE_TOOL_NAME}
        can_gain_evidence = any(
            tool["function"]["name"] not in read_tool_names for tool in state.configured_tools
        )
        toolbox = state.workspace_tools
        available = []
        for tool in state.configured_tools:
            name = tool["function"]["name"]
            if name == GET_EVIDENCE_TOOL_NAME:
                if state.budget.reads_exhausted or not (can_gain_evidence or len(state.evidence_store)):
                    continue
            elif name == READ_WEB_PAGE_TOOL_NAME:
                if state.budget.reads_exhausted or not (
                    can_gain_evidence or state.evidence_store.has_web_records()
                ):
                    continue
            elif toolbox is not None and toolbox.is_write(name):
                if state.budget.write_proposals_exhausted or state.approval_pending:
                    continue
            elif toolbox is not None and toolbox.uses_read_budget(name):
                if state.budget.reads_exhausted:
                    continue
            elif state.budget.tool_calls_exhausted:
                continue
            available.append(tool)
        return available

    # 保存情報と既知URLの本文を、検索とは独立した読み取り予算で取得する。
    # Read stored evidence or a known page using a budget independent of searches.
    def _run_read_tool_call(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
    ) -> None:
        budget = state.budget
        name = tool_call.get("function", {}).get("name")
        if budget.reads_exhausted:
            payload = {
                "status": "step_limit_reached",
                "message": "The reading budget has been reached. Use the evidence already read.",
            }
        else:
            budget.start_read_call()
            state.telemetry.tool_calls = budget.tool_calls
            arguments = tool_call.get("function", {}).get("arguments", "{}")
            if name == READ_WEB_PAGE_TOOL_NAME:
                payload = state.web_page_reader.execute_read_web_page(
                    arguments, max_chars=budget.read_message_limit,
                )
                if payload.get("status") == "ok":
                    state.web_search_trace_steps.append(TraceStep(
                        title="参照先のページ本文を確認",
                        detail="以前に見つけたURLから、回答に必要な箇所を読みました。",
                        kind="read",
                    ))
            else:
                payload = state.evidence_store.execute_get_evidence(
                    arguments, max_chars=budget.read_message_limit,
                )
                if _includes_external_evidence(payload):
                    state.untrusted_input_ingested = True
            budget.consume_read_chars(len(json.dumps(payload, ensure_ascii=False)))
            state.telemetry.evidence_read_count = budget.read_calls
            state.telemetry.read_budget_consumed = budget.read_chars
            state.turn_state.record_search(
                tool_name=str(name),
                status=str(payload.get("status") or "unknown"),
            )
        state.current_messages.append(_tool_result_message(tool_call, payload))

    # 未対応ツールの要求を記録し、モデルへ理由を返すフェーズ。
    # The phase that records an unsupported tool request and tells the model why.
    def _record_unsupported_tool_call(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
        func_name: Any,
    ) -> None:
        if not state.budget.tool_calls_exhausted:
            state.budget.start_tool_call()
        elif not state.budget.reads_exhausted:
            # 取り下げ済みツールを繰り返すモデルにも有限の試行回数を適用する。
            # An unavailable tool must not create an unbounded decision loop.
            state.budget.start_read_call()
        state.telemetry.tool_calls = state.budget.tool_calls
        state.turn_state.record_search(
            tool_name=str(func_name or "unknown_tool"),
            status="unsupported_tool",
        )
        state.current_messages.append(
            _tool_result_message(
                tool_call,
                {
                    "status": "unsupported_tool",
                    "message": f"Unsupported tool: {func_name}",
                },
            )
        )
