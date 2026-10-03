"""ターン状態の構築と、TurnState を軸にした単一判断ループのフェーズ。

The phase that builds the turn state and drives the single decision loop around TurnState.

モデル判断のストリームは `_iter_llm_stream_with_retry`、ツールの提示と実行は
`chat_generation_tools`、回答の配信は `chat_generation_answer_stream` の各メソッドを呼ぶ。
The model decision is streamed through `_iter_llm_stream_with_retry`; offering and running tools
is `chat_generation_tools`, and delivering the answer is `chat_generation_answer_stream`.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .chat_agent_budget import AgentStepBudget
from .chat_context_recovery import build_recovery_base_messages
from .chat_evidence_store import EvidenceStore
from .chat_generation_job_base import (
    ChatGenerationJobBase,
    _latest_user_message_text,
)
from .chat_generation_turn import ChatTurnRunState, ModelDecision
from .chat_input_budget import estimate_messages_chars
from .chat_prompt import insert_before_latest_user_message
from .chat_tool_calls import (
    _contains_unconfirmed_context_facts,
    _parse_tool_calls_chunk,
)
from .chat_turn_state import (
    TurnStateUpdateFilter,
    build_turn_loop_messages,
    parse_turn_state_update,
    strip_turn_state_update_chunks,
)
from .chat_url_context import (
    PASTED_URL_EARLIER_STATUS,
    PASTED_URL_STATUS,
    PASTED_URL_TOOL_NAME,
    pasted_url_evidence_id,
)
from .chat_web_page_reader import WebPageReader
from .chat_write_claim_guard import _unconfirmed_write_claim_fallback
from .llm import (
    LlmAuthenticationError,
    LlmConfigurationError,
    LlmInputLimitError,
    LlmInvalidModelError,
    LlmServiceError,
    LlmToolSchemaError,
)
from .llm_context_budget import (
    estimate_request_tokens,
    get_context_budget,
    request_fits_context,
)
from .research_state import (
    TurnState,
    TurnStateProjectionError,
)
from .selected_reference_context import (
    PERSONAL_KNOWLEDGE_SOURCE,
    SHARED_PROMPT_SOURCE,
)
from .web_search import (
    build_web_search_evidence_policy_message,
    create_web_evidence_context_budget,
    create_web_page_fetch_budget,
)
from .web_search_trace import selected_reference_steps

logger = logging.getLogger(__name__)


# ターン状態の構築と判断ループを担う Mixin
# Mixin that builds the turn state and drives the decision loop
class ChatGenerationAgentLoopMixin(ChatGenerationJobBase):
    # ターン開始時の状態を組み立てる。既存の参照根拠と選択済み参照をここで取り込む。
    # Build the turn's starting state, seeding it with prior evidence and selected references.
    def _build_turn_run_state(self) -> ChatTurnRunState:
        budget = AgentStepBudget.from_environment()
        telemetry = self._telemetry
        # 根拠の予算は許可されたツール実行回数から算出する。予算が回数に足りないと、
        # 後半の検索が「中身ゼロで成功した検索結果」に化けてモデルを誤誘導する。
        # Size the evidence budget from the permitted tool calls: a budget that cannot cover
        # them turns later searches into "successful" results with no content at all.
        evidence_context_budget = create_web_evidence_context_budget(budget.max_tool_calls)
        telemetry.evidence_budget_max_chars = evidence_context_budget.max_chars
        latest_user_message = _latest_user_message_text(self._conversation_messages)
        evidence_store = EvidenceStore()
        # 原文は初期値。最初のモデル判断で履歴を踏まえた目的へ更新する。
        # The raw request is a seed; the first model decision resolves it in context.
        turn_state = TurnState(objective=latest_user_message)
        state = ChatTurnRunState(
            # キャンセル時に保存できるよう、インスタンス側のチャンクリストを共有する。
            # Share the instance chunk list so a cancel can persist the partial text.
            chunks=self._chunks,
            telemetry=telemetry,
            budget=budget,
            page_fetch_budget=create_web_page_fetch_budget(),
            evidence_context_budget=evidence_context_budget,
            evidence_store=evidence_store,
            web_page_reader=WebPageReader(evidence_store),
            turn_state=turn_state,
            turn_base_messages=[dict(message) for message in self._conversation_messages],
            latest_user_message=latest_user_message,
            selected_web_search_images=self._selected_web_search_images,
            continuation_state_filter=TurnStateUpdateFilter(),
            web_search_trace_steps=selected_reference_steps(self._selected_reference_trace),
            workspace_tools=self._workspace_tools,
            # 停止時に保存できるよう、インスタンス側の承認カードのリストを共有する。
            # Share the instance card list so a stop can persist the cards too.
            tool_approval_parts=self._tool_approval_parts,
            untrusted_input_ingested=self._starts_with_external_input(),
        )
        self._register_pasted_url_pages(state)
        for prior_result in self._prior_web_search_results:
            turn_state.record_search(
                tool_name="web_search",
                query=prior_result.query,
                searched_at=prior_result.searched_at,
                freshness=prior_result.freshness,
                evidence_refs=evidence_store.add_web_result(prior_result),
                status="prior_turn",
            )
        for selected_trace in self._selected_reference_trace:
            if (
                selected_trace.source == PERSONAL_KNOWLEDGE_SOURCE
                and _contains_unconfirmed_context_facts(selected_trace.payload)
            ):
                # 選択済み参照と、検索0件時に注入する概観にもツール検索と同じ自動承認ゲートを適用する。
                # Selected references and the no-match overview enter the prompt before the job
                # starts; they must hold the same auto-approval gate as tool-driven lookups.
                state.untrusted_input_ingested = True
            selected_refs = evidence_store.add_reference_payload(
                selected_trace.payload,
                source_type=selected_trace.source,
                query=selected_trace.query,
            )
            turn_state.record_search(
                tool_name=selected_trace.source,
                query=selected_trace.query,
                evidence_refs=selected_refs,
                status=str(selected_trace.payload.get("status") or "ok"),
            )
        return state

    # ターンの開始時点で外部の内容を読んでいるか。貼り付け URL の本文、他人の公開投稿の事前検索、
    # 呼び出し側が伝える添付などが該当する。自分のメモを読んだだけなら当たらない。
    # Whether the turn starts having read external content: pasted page bodies, a prefetch of
    # other people's public posts, or attachments the caller reports. Reading one's own memos
    # does not count.
    def _starts_with_external_input(self) -> bool:
        if self._pasted_url_pages:
            return True
        if any(trace.source == SHARED_PROMPT_SOURCE for trace in self._selected_reference_trace):
            return True
        return bool(self._workspace_tools and self._workspace_tools.external_input_in_turn)

    # 貼り付けURLの本文を、検索結果とは別経路で根拠に載せる。抜粋は既に発話へ前置済みなので、
    # ここで登録するのは「続きを分割して読むための入口」である。
    # Register pasted page bodies as evidence on a path of their own. The excerpt is already in
    # the message; what is registered here is the entry point for reading the rest in chunks.
    def _register_pasted_url_pages(self, state: ChatTurnRunState) -> None:
        registered_ids: set[str] = set()
        for page in self._pasted_url_pages:
            reference = state.evidence_store.add_pasted_page(
                url=page.url,
                title=page.title,
                snippet=page.snippet,
                fetched_at=page.fetched_at,
            )
            if reference is None:
                continue
            registered_ids.add(str(reference["evidence_id"]))
            state.web_page_reader.seed_page(
                page.url,
                text=page.text,
                title=page.title,
                final_url=page.final_url,
                fetched_at=page.fetched_at,
            )
            state.turn_state.record_search(
                tool_name=PASTED_URL_TOOL_NAME,
                query=page.url,
                evidence_refs=(reference,),
                searched_at=page.fetched_at,
                status=PASTED_URL_STATUS,
            )
        # 過去ターンのURLは本文を持たないまま登録する。読み取り時に WebPageReader が
        # 既存のSSRF対策付き経路で取得するので、使われなかったURLは通信を起こさない。
        # Earlier URLs are registered without a body. WebPageReader fetches through the existing
        # SSRF-guarded path only when the page is actually read, so unused URLs cost nothing.
        for url in self._earlier_pasted_urls:
            # 本文付きで登録済みのURLをここで上書きすると、抜粋も種も失われる。登録前に弾く。
            # Registering a seeded URL again here would replace its snippet and title with
            # nothing, so the skip has to happen before the store is touched.
            if pasted_url_evidence_id(url) in registered_ids:
                continue
            reference = state.evidence_store.add_pasted_page(url=url)
            if reference is None:
                continue
            registered_ids.add(str(reference["evidence_id"]))
            state.turn_state.record_search(
                tool_name=PASTED_URL_TOOL_NAME,
                query=url,
                evidence_refs=(reference,),
                status=PASTED_URL_EARLIER_STATUS,
            )

    # 1回のモデル判断へ渡す要求を TurnState と直近のツール結果だけから組み立てるフェーズ。
    # The phase that builds one decision request from TurnState plus only the newest tool result.
    def _prepare_turn_messages(
        self,
        state: ChatTurnRunState,
        latest_tool_exchange: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        force_answer: bool,
        minimal: bool = False,
        empty_answer_recovery: bool = False,
    ) -> list[dict[str, Any]] | None:
        """Build one decision request from TurnState plus only the newest tool result.

        ``minimal`` はプロバイダ側の拒否からの再構築用。生のツール結果を落とし、
        TurnState と直前の会話・最新の依頼で同じ判断をやり直す。
        ``minimal`` rebuilds after a provider-side rejection: the raw tool result is
        dropped and the same decision is retried with TurnState and the recent exchange.
        ``empty_answer_recovery`` は直前の判断が本文を返さなかった回復用で、
        内部封筒を要求しない回復契約に置き換える。
        ``empty_answer_recovery`` marks the retry after a decision that produced no
        user-facing answer; it replaces the contract without requiring another state envelope.
        """
        telemetry = state.telemetry
        phase = "agent"
        context_budget = get_context_budget(self._model, phase, tools)
        # 承認待ちで締める回答では、ツール結果が落ちる代わりにサーバーの要約を渡す。
        # A reply closing on pending approvals gets the server's summary in place of the dropped
        # tool results.
        approval_pending_summaries = state.approval_pending_summaries if state.approval_pending else ()
        state_tokens = min(
            6_000,
            max(1_000, context_budget.available_input_tokens // 3),
        )

        def with_web_policy(
            projection: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            # 検索根拠を持つターンだけ、引用と回答の方針を1つのsystem指示として渡す。
            # A turn holding web evidence gets the citation and answering policy as one
            # system instruction; an ordinary chat turn never carries it.
            if not (state.web_search_results or self._prior_web_search_results):
                return projection
            return insert_before_latest_user_message(
                projection,
                build_web_search_evidence_policy_message(),
            )

        if not minimal:
            try:
                projected = state.turn_state.projected_messages(
                    state.turn_base_messages,
                    max_tokens=state_tokens,
                )
            except TurnStateProjectionError:
                return None
            candidate = build_turn_loop_messages(
                [
                    *with_web_policy(projected),
                    *([] if force_answer else latest_tool_exchange),
                ],
                force_answer=force_answer,
                empty_answer_recovery=empty_answer_recovery,
                workspace_action_recovery=(
                    state.workspace_action_recovery_attempted and not state.tool_approval_parts and not force_answer
                ),
                approval_pending_summaries=approval_pending_summaries,
            )
            if request_fits_context(candidate, self._model, phase, tools):
                telemetry.context_projection_count += 1
                return candidate

        try:
            minimal_projected = state.turn_state.projected_messages(
                build_recovery_base_messages(state.turn_base_messages),
                max_tokens=state_tokens,
            )
        except TurnStateProjectionError:
            return None
        minimal_candidate = build_turn_loop_messages(
            [
                *with_web_policy(minimal_projected),
                *([] if minimal or force_answer else latest_tool_exchange),
            ],
            force_answer=force_answer,
            empty_answer_recovery=empty_answer_recovery,
            workspace_action_recovery=(
                state.workspace_action_recovery_attempted and not state.tool_approval_parts and not force_answer
            ),
            approval_pending_summaries=approval_pending_summaries,
        )
        if request_fits_context(minimal_candidate, self._model, phase, tools):
            telemetry.context_projection_count += 1
            telemetry.context_recovery_count += 1
            return minimal_candidate
        return None

    # 単一判断ループ: TurnStateを見る → 必要ならツール → State更新 → 再判断。
    # ツール履歴全体は再送せず、直近の呼び出しと結果だけを次の判断へ渡す。
    # The single-decision loop: read TurnState, optionally run tools, update state, decide again.
    # Only the newest call and its result are replayed, never the whole tool history.
    def _run_agent_loop(self, state: ChatTurnRunState) -> bool:
        """Drive the decision loop; return True when a stop request ended the turn."""
        budget = state.budget
        telemetry = state.telemetry
        while True:
            if self._should_stop():
                return True

            # モデル判断の上限は、回復用の再試行（入力超過・ツールスキーマ・空回答・
            # 調査失敗）も含めてここで最終的に押さえる。通常は最後の1回が回答へ
            # 予約されているため到達しないが、再試行が重なった場合の歯止めになる。
            # This is the final stop on model decisions, covering the recovery replays
            # (input limit, tool schema, empty answer, research failure) as well. The
            # reserved final answer turn normally keeps the loop away from it; it exists
            # so stacked replays cannot run past the budget.
            if budget.llm_turns >= budget.max_llm_turns:
                telemetry.llm_turn_budget_exhausted = True
                logger.warning(
                    "Stopping the agent loop at the model-decision budget.",
                    extra=telemetry.as_log_extra(),
                )
                self._salvage_pending_answer_text(state)
                return False

            available_tools = self._offered_agent_tools(state)
            tools_withdrawn = not available_tools
            # 未提出のメモ操作を空回答で打ち切らない。カード作成前は既存のツールと
            # 直近の結果を残して一度やり直し、それ以外は従来の回答のみ回復にする。
            # Keep tools and the last result for unsubmitted workspace actions during recovery.
            force_answer = tools_withdrawn or (
                state.empty_answer_recovery_attempted
                and (self._workspace_tools is None or bool(state.tool_approval_parts))
            )
            active_tools = None if force_answer else available_tools
            # 承認待ちでツールを外すのは予算切れではないので、予算枯渇としては数えない。
            # Withdrawing tools for a pending approval is not budget exhaustion, so it is not
            # counted as such.
            if tools_withdrawn and not state.tools_disabled_after_failure and not state.approval_pending:
                telemetry.tools_withdrawn_by_budget = True
            turn_messages = self._prepare_turn_messages(
                state,
                state.current_messages,
                active_tools,
                force_answer=force_answer,
                minimal=(
                    state.minimal_context_required
                    or state.tool_schema_recovery_attempted
                    or state.tools_disabled_after_failure
                ),
                empty_answer_recovery=state.empty_answer_recovery_attempted,
            )
            if turn_messages is None:
                telemetry.context_recovery_count += 1
                raise LlmInputLimitError(
                    "The complete TurnState does not fit the model context budget."
                )
            llm_step = budget.start_llm_turn()
            telemetry.llm_turns = budget.llm_turns

            if not state.suppress_next_generation_started:
                self._publish(
                    "response_generation_started",
                    {"step": llm_step, "max_steps": budget.max_steps},
                )
            state.suppress_next_generation_started = False

            try:
                decision = self._stream_model_decision(
                    state,
                    turn_messages,
                    active_tools,
                    force_answer=force_answer,
                )
            except LlmServiceError as exc:
                # 調査ステップがプロバイダ障害で落ちただけでターン全体を失敗させない。
                # ツールを外せば要求は小さく単純になり、ここまでに集めた根拠で回答へ
                # 縮退できる。1ターンに複数回のモデル判断がある以上、この縮退が無いと
                # 失敗機会が呼び出し回数ぶん積み上がる。
                # A provider failure during a research step must not fail the whole turn.
                # Dropping the tools makes the request smaller and simpler, so the turn can
                # degrade to an answer built from the evidence already gathered. Without this
                # the failure odds compound with every model decision in the turn.
                if not self._can_degrade_to_answer(state, active_tools, exc):
                    raise
                state.research_failure_recovery_attempted = True
                state.tools_disabled_after_failure = True
                telemetry.research_failure_recoveries += 1
                logger.warning(
                    "Research step failed; answering from the evidence already gathered "
                    "(error=%s).",
                    exc.__class__.__name__,
                    exc_info=exc,
                    extra=telemetry.as_log_extra(),
                )
                with self._chunks_lock:
                    self._pending_stream_chunks = []
                    self._pending_stream_is_rewrite = False
                state.suppress_next_generation_started = True
                continue
            if decision.outcome == "stopped":
                return True
            if decision.outcome == "replay":
                continue

            if not decision.tool_calls:
                if self._finish_answer_step(
                    state,
                    turn_messages,
                    active_tools,
                    decision.step_chunks,
                ):
                    continue
                return False

            with self._chunks_lock:
                self._pending_stream_chunks = []
                self._pending_stream_is_rewrite = False
            telemetry.research_phase_used = True
            self._dispatch_tool_calls(state, decision.tool_calls, llm_step)

    # モデル判断1回をストリームし、本文チャンクとツール呼び出しへ振り分けるフェーズ。
    # The phase that streams one model decision and splits it into body chunks and tool calls.
    def _stream_model_decision(
        self,
        state: ChatTurnRunState,
        turn_messages: list[dict[str, Any]],
        active_tools: list[dict[str, Any]] | None,
        *,
        force_answer: bool,
    ) -> ModelDecision:
        tool_calls_buffer: list[dict[str, Any]] = []
        step_chunks: list[str] = []
        with self._chunks_lock:
            self._pending_stream_chunks = step_chunks
            self._pending_stream_is_rewrite = False
        try:
            for chunk in self._iter_llm_stream_with_retry(
                turn_messages,
                tools=active_tools,
                generation_phase="agent",
                discard_partial_on_retry=True,
                tolerate_output_limit=True,
            ):
                if self._should_stop():
                    return ModelDecision(outcome="stopped")
                if not chunk:
                    continue
                parsed_tool_calls = _parse_tool_calls_chunk(chunk)
                if parsed_tool_calls is not None:
                    tool_calls_buffer.extend(parsed_tool_calls)
                else:
                    # `step_chunks` は `self._pending_stream_chunks` と同一オブジェクト
                    # （直前で代入済み）。cancel() 側の読み取りと同じロックで追記する。
                    # `step_chunks` is the very same object as `self._pending_stream_chunks`
                    # (assigned above); append it under the same lock cancel() reads with.
                    with self._chunks_lock:
                        step_chunks.append(chunk)
        except LlmInputLimitError:
            # 同じ要求を送り直しても同じ拒否になる。生のツール結果を捨て、
            # TurnState と直前の会話を残して同じ判断を1度だけやり直す。
            # Resending the identical request only repeats the rejection: drop the raw
            # tool result and retry once with TurnState and the recent exchange.
            if state.minimal_context_required or state.chunks:
                raise
            state.minimal_context_required = True
            state.telemetry.input_limit_recoveries += 1
            state.telemetry.context_recovery_count += 1
            with self._chunks_lock:
                self._pending_stream_chunks = []
                self._pending_stream_is_rewrite = False
            state.suppress_next_generation_started = True
            return ModelDecision(outcome="replay")
        except LlmToolSchemaError:
            # ツール予算切れ後のツールなし要求がモデルの逸脱で拒否された場合は、
            # 直前の会話を残し、ツール履歴を除いた最終回答要求へ1度だけ切り替える。
            # If the model violates the tool-free request after the budget is exhausted,
            # retry once with a compact final-answer request retaining the recent
            # conversation but excluding tool history.
            if (
                force_answer
                and active_tools is None
                and not state.tool_schema_recovery_attempted
                and not self._cancelled
            ):
                state.tool_schema_recovery_attempted = True
                state.telemetry.tool_schema_recoveries += 1
                with self._chunks_lock:
                    self._pending_stream_chunks = []
                    self._pending_stream_is_rewrite = False
                state.suppress_next_generation_started = True
                return ModelDecision(outcome="replay")
            raise

        if self._should_stop():
            return ModelDecision(outcome="stopped")

        turn_state_update = parse_turn_state_update(step_chunks)
        # 封筒は次の判断へ状態を渡すためのもので、契約はツールを呼ぶ判断にだけ求める。そのまま
        # 回答する判断と、封筒を省かせる回復ステップに封筒が無いのは契約どおりなので数えない。
        # The envelope carries state into the next decision, so the contract asks for it only on a
        # decision that calls a tool. A direct answer, or a recovery step told to omit the envelope,
        # follows the contract without one and is not counted.
        if (
            turn_state_update is None
            and tool_calls_buffer
            and not force_answer
            and not state.empty_answer_recovery_attempted
        ):
            state.telemetry.missing_turn_state_updates += 1
        state.turn_state.apply_model_update(turn_state_update)
        return ModelDecision(
            outcome="decided",
            tool_calls=[] if force_answer else tool_calls_buffer,
            step_chunks=step_chunks,
        )

    # ツール要求の無い判断を締める。回復が必要なら配信せず、True を返して同じループを続ける。
    # Close a decision without tool calls; True requests recovery before publishing its answer.
    def _finish_answer_step(
        self,
        state: ChatTurnRunState,
        turn_messages: list[dict[str, Any]],
        active_tools: list[dict[str, Any]] | None,
        step_chunks: list[str],
    ) -> bool:
        telemetry = state.telemetry
        output_limited = self._last_stream_output_limited
        with self._chunks_lock:
            self._pending_stream_chunks = []
            self._pending_stream_is_rewrite = False
            # 停止済みかはバッファを空にするのと同じロックの下で読む。cancel() はこのロックの
            # 下でバッファを取り出して判定するので、停止済みならこのステップの本文は cancel()
            # の持ち分であり、ここでタグ無し封筒を読むと同じ出力を二重に数える。判定全体を
            # ロック下に置く案より、ロックを短く保てるこちらを選んだ。
            # Read the stop flag under the same lock that empties the buffer. cancel() takes and
            # judges the buffer under this lock, so once stopped this step's text belongs to
            # cancel(), and reading the untagged envelope here too would count the same output
            # twice. Chosen over running the whole check under the lock to keep the lock short.
            cancelled = self._cancelled
        # モデルの区切りをそのまま保ち、内部状態の封筒だけを取り除く。
        # Keep the model's own boundaries and drop only the internal envelope.
        visible_chunks = strip_turn_state_update_chunks(step_chunks)
        untagged_update = (
            None if cancelled else self._untagged_turn_state_update(step_chunks, "".join(visible_chunks))
        )
        if untagged_update is not None:
            # タグを落とした封筒は状態の更新として読み、本文は空として扱う。回答として
            # 保存すると内部 JSON がそのまま done になり、空回答の回復も働かない。
            # Read an envelope that lost its tags as the state update and treat the body as
            # empty. Saving it as the answer would finish the turn as done with internal JSON
            # and bypass the empty-answer recovery.
            state.turn_state.apply_model_update(untagged_update)
            telemetry.untagged_turn_state_recoveries += 1
            visible_chunks = []
        if (
            visible_chunks
            and self._workspace_tools is not None
            and active_tools
            and not state.tool_approval_parts
            and not state.workspace_action_recovery_attempted
            and not cancelled
            and not output_limited
            and _unconfirmed_write_claim_fallback("".join(visible_chunks), state.latest_user_message) is not None
        ):
            # 訂正も通常ループの判断予算を使う。結果や承認を捏造せず、同じツールで再判断させる。
            # Use the normal decision budget; let the model submit through the existing tools.
            state.workspace_action_recovery_attempted = True
            telemetry.workspace_action_recoveries += 1
            state.suppress_next_generation_started = True
            return True
        if (
            not visible_chunks
            and not state.chunks
            and not state.empty_answer_recovery_attempted
            and not self._cancelled
        ):
            # 封筒のみ（タグの有無を問わない）・無出力・出力上限で本文ゼロは「回答なし」。
            # ここで抜けると画像だけ／トレースだけの応答が完了扱いになるため、同じ判断を
            # 1度だけやり直す。未提出のメモ操作がありうる場合はツールを残す。
            # Envelope-only (tagged or not), empty, or cut off before any body text means no
            # answer. Breaking here would finish the turn as an image-only or
            # trace-only reply, so retry once, retaining tools for unsubmitted workspace actions.
            state.empty_answer_recovery_attempted = True
            telemetry.empty_answer_recoveries += 1
            logger.warning(
                "Final decision produced no user-facing answer; retrying once "
                "with the applicable recovery contract.",
                extra={
                    **telemetry.as_log_extra(),
                    "output_limited": output_limited,
                    "step_chars": len("".join(step_chunks)),
                },
            )
            state.suppress_next_generation_started = True
            return True
        state.answer_context_messages = turn_messages
        telemetry.final_answer_input_tokens = estimate_request_tokens(
            turn_messages,
            active_tools,
        )
        telemetry.final_answer_input_chars = estimate_messages_chars(turn_messages)
        telemetry.first_pass_finish_reason = (
            "max_output_tokens" if output_limited else "stop"
        )
        if visible_chunks:
            visible_text = "".join(visible_chunks)
            if output_limited and self._workspace_tools is not None:
                fallback = _unconfirmed_write_claim_fallback(
                    visible_text, state.latest_user_message, state.tool_approval_parts
                )
                if fallback is not None:
                    self._publish_completed_answer_step(state, [fallback])
                    return False
                sentence_boundaries = list(re.finditer(r"[。！？!?]|\.(?=[ \t\n]|$)", visible_text))
                split_at = sentence_boundaries[-1].end() if sentence_boundaries else 0
                if split_at:
                    self._publish_completed_answer_step(state, [visible_text[:split_at]])
                with self._chunks_lock:
                    memo_tail_start = len(state.chunks)
                    if split_at < len(visible_text):
                        state.chunks.append(visible_text[split_at:])
                state.final_answer_incomplete = self._continue_interrupted_answer(
                    state,
                    turn_messages,
                    visible_text,
                    memo_tail_start=memo_tail_start,
                )
            else:
                self._publish_completed_answer_step(state, visible_chunks)
            if output_limited and self._workspace_tools is None:
                # 出力上限で切れた回答は成功完了にしない。同じ回答の続きだけを
                # 限定回数で取り直す。
                # An answer cut off at the output cap is not a success: fetch
                # only the remainder, a bounded number of times.
                state.final_answer_incomplete = self._continue_interrupted_answer(
                    state,
                    turn_messages,
                    "".join(visible_chunks),
                )
        return False

    # 失敗した調査ステップを、ツールなしの回答へ縮退させてよいかを判定する。
    # Decide whether a failed research step may degrade into a tool-free answer.
    def _can_degrade_to_answer(
        self,
        state: ChatTurnRunState,
        active_tools: list[dict[str, Any]] | None,
        exc: BaseException,
    ) -> bool:
        if self._cancelled or state.research_failure_recovery_attempted:
            return False
        # ツールを外した要求で落ちたのなら、外すことによる回復は望めない。
        # A request that already carried no tools cannot be helped by removing them.
        if active_tools is None:
            return False
        # 設定・認証・モデル指定の誤りは、何度やり直しても同じ結果になる。
        # Configuration, authentication and model errors reproduce on every retry.
        if isinstance(
            exc,
            (LlmConfigurationError, LlmAuthenticationError, LlmInvalidModelError),
        ):
            return False
        return isinstance(exc, LlmServiceError)
