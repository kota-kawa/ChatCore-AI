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
    tools_withdrawn_by_budget: bool = False
    research_phase_used: bool = False
    research_summary_present: bool = False
    research_wrapup_used: bool = False
    research_draft_forwarded: bool = False
    coverage_requirement_count: int = 0
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
            "tools_withdrawn_by_budget": self.tools_withdrawn_by_budget,
            "research_phase_used": self.research_phase_used,
            "research_summary_present": self.research_summary_present,
            "research_wrapup_used": self.research_wrapup_used,
            "research_draft_forwarded": self.research_draft_forwarded,
            "coverage_requirement_count": self.coverage_requirement_count,
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
        }
