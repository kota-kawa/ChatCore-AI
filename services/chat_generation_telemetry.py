# 通常チャット1ターン分の生成テレメトリを集約する。長いステップのターンで
# 「回答が短い（不足生成）」と「回答が途中で切れた（打ち切り）」を切り分けるために使う。
# 集計値だけを持ち、本文・検索結果・ユーザー入力そのものは保持しない。
# Aggregates per-turn generation telemetry for normal chat. It exists to separate
# under-generation ("the answer got short") from truncation ("the answer was cut off")
# on long, many-step turns. It holds counters only, never bodies, evidence, or user input.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 継続理由は決まった語彙だけを記録し、プロバイダのメッセージ本文をログへ流さない。
# Continuation reasons are recorded from a fixed vocabulary so provider message bodies
# never reach the logs.
CONTINUATION_REASON_MAX_ITEMS = 8
ARTIFACT_REASON_CODE_MAX_ITEMS = 8


@dataclass
class ChatGenerationTelemetry:
    """Mutable per-turn counters rendered into one structured log record."""

    model: str = ""
    # 会話モデルの推論ターン数と、実際に実行したツール数を別々に数える。
    # Count model reasoning turns separately from executed tool calls.
    llm_turns: int = 0
    tool_calls: int = 0
    web_search_count: int = 0
    cached_web_search_count: int = 0
    lookup_call_count: int = 0
    evidence_read_count: int = 0
    read_budget_consumed: int = 0
    tools_withdrawn_by_budget: bool = False
    research_phase_used: bool = False
    final_answer_input_tokens: int = 0
    final_answer_input_chars: int = 0
    final_answer_output_chars: int = 0
    first_pass_finish_reason: str = ""
    continuation_count: int = 0
    continuation_reasons: list[str] = field(default_factory=list)
    continuation_stalled: bool = False
    continuation_restart_trimmed: bool = False
    evidence_budget_max_chars: int = 0
    evidence_budget_consumed: int = 0
    empty_evidence_payloads: int = 0
    truncated_evidence_payloads: int = 0
    input_limit_recoveries: int = 0
    research_output_limit_recoveries: int = 0
    # Context preparation counters. They contain sizes and counts only, never prompt bodies.
    context_projection_count: int = 0
    context_compaction_count: int = 0
    context_recovery_count: int = 0
    # プロバイダがツール呼び出しを拒否し、ツールなしでやり直して回復した回数。
    # How often a provider rejected a tool call and the step recovered without tools.
    tool_schema_recoveries: int = 0
    # 最後の判断が本文を返さず、回答のみ要求で1度やり直した回数。
    # How often the final decision produced no user-facing answer and was retried answer-only.
    empty_answer_recoveries: int = 0
    # タグの無い封筒 JSON だけの本文を封筒として扱い、回答にしなかった回数。
    # How often a body holding only an untagged envelope JSON was treated as the envelope.
    untagged_turn_state_recoveries: int = 0
    # 調査ステップがプロバイダ障害で落ち、ツールを外した回答へ縮退した回数。
    # How often a provider failure during research degraded the turn to a tool-free answer.
    research_failure_recoveries: int = 0
    # 失敗したターンから、配信前のバッファに残っていた本文を救出した回数。
    # How often a failed turn salvaged body text still sitting in the pre-publish buffer.
    salvaged_partial_answers: int = 0
    # モデル判断の上限に達してループを打ち切ったか。
    # Whether the loop stopped because the model-decision budget ran out.
    llm_turn_budget_exhausted: bool = False
    # 生成UIの5段階（判定・注入・抽出／検証・修復・実行）を、モデル別の成功率として
    # 集計できるようにする。理由コードは services/generative_ui_status.py の固定語彙のみ。
    # Makes the five generated-UI stages (decision, injection, extraction/validation, repair,
    # execution) countable per model. Reason codes come only from the fixed vocabulary in
    # services/generative_ui_status.py.
    ui_mode: str = ""
    # decided / failed / disabled のいずれか。判定失敗を NONE と混同しないために分ける。
    # One of decided / failed / disabled, kept apart so a failed decision is never read as NONE.
    ui_mode_decision_status: str = ""
    explicit_ui_opt_out: bool = False
    artifact_status: str = "not_requested"
    artifact_reason_codes: list[str] = field(default_factory=list)
    artifact_repair_attempted: bool = False
    artifact_repair_succeeded: bool = False
    artifact_repair_output_limited: bool = False

    @property
    def agent_steps(self) -> int:
        """Total displayed steps: model turns plus executed tool calls."""
        return self.llm_turns + self.tool_calls

    def record_continuation_reason(self, reason: str) -> None:
        normalized = str(reason or "").strip()[:64]
        if not normalized:
            return
        if len(self.continuation_reasons) >= CONTINUATION_REASON_MAX_ITEMS:
            return
        self.continuation_reasons.append(normalized)

    def record_evidence_payload(self, *, empty: bool, truncated: bool) -> None:
        if empty:
            self.empty_evidence_payloads += 1
        elif truncated:
            self.truncated_evidence_payloads += 1

    def record_generated_ui_outcome(
        self,
        *,
        status: str,
        reason_codes: list[str],
        repair_attempted: bool,
    ) -> None:
        """Record the outcome of one generated-UI turn from its normalized response."""
        self.artifact_status = status
        self.artifact_reason_codes = list(reason_codes)[:ARTIFACT_REASON_CODE_MAX_ITEMS]
        self.artifact_repair_attempted = repair_attempted
        self.artifact_repair_succeeded = repair_attempted and status == "valid"
        self.artifact_repair_output_limited = (
            "artifact_repair_output_limited" in self.artifact_reason_codes
        )

    def as_log_extra(self) -> dict[str, Any]:
        """Render the counters as one flat structured-log payload."""
        return {
            "model": self.model,
            "agent_steps": self.agent_steps,
            "llm_turns": self.llm_turns,
            "tool_calls": self.tool_calls,
            "web_search_count": self.web_search_count,
            "cached_web_search_count": self.cached_web_search_count,
            "lookup_call_count": self.lookup_call_count,
            "evidence_read_count": self.evidence_read_count,
            "read_budget_consumed": self.read_budget_consumed,
            "tools_withdrawn_by_budget": self.tools_withdrawn_by_budget,
            "research_phase_used": self.research_phase_used,
            "final_answer_input_tokens": self.final_answer_input_tokens,
            "final_answer_input_chars": self.final_answer_input_chars,
            "final_answer_output_chars": self.final_answer_output_chars,
            "first_pass_finish_reason": self.first_pass_finish_reason,
            "continuation_count": self.continuation_count,
            "continuation_reasons": list(self.continuation_reasons),
            "continuation_stalled": self.continuation_stalled,
            "continuation_restart_trimmed": self.continuation_restart_trimmed,
            "evidence_budget_max_chars": self.evidence_budget_max_chars,
            "evidence_budget_consumed": self.evidence_budget_consumed,
            "empty_evidence_payloads": self.empty_evidence_payloads,
            "truncated_evidence_payloads": self.truncated_evidence_payloads,
            "input_limit_recoveries": self.input_limit_recoveries,
            "research_output_limit_recoveries": self.research_output_limit_recoveries,
            "context_projection_count": self.context_projection_count,
            "context_compaction_count": self.context_compaction_count,
            "context_recovery_count": self.context_recovery_count,
            "tool_schema_recoveries": self.tool_schema_recoveries,
            "empty_answer_recoveries": self.empty_answer_recoveries,
            "untagged_turn_state_recoveries": self.untagged_turn_state_recoveries,
            "research_failure_recoveries": self.research_failure_recoveries,
            "salvaged_partial_answers": self.salvaged_partial_answers,
            "llm_turn_budget_exhausted": self.llm_turn_budget_exhausted,
            "ui_mode": self.ui_mode,
            "ui_mode_decision_status": self.ui_mode_decision_status,
            "explicit_ui_opt_out": self.explicit_ui_opt_out,
            "artifact_status": self.artifact_status,
            "artifact_reason_codes": list(self.artifact_reason_codes),
            "artifact_repair_attempted": self.artifact_repair_attempted,
            "artifact_repair_succeeded": self.artifact_repair_succeeded,
            "artifact_repair_output_limited": self.artifact_repair_output_limited,
        }
