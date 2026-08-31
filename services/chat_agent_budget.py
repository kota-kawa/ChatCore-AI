# 通常チャットのエージェントループが1ターンで使える予算を決める。
# 推論ターンとツール実行を別々に数えるのが要点で、単一カウンタを共有すると
# 検索を1回増やすたびに推論ターンが1回減り、調査が深いターンほど統合が痩せる。
# Owns the per-turn budget for the normal-chat agent loop. The point is that reasoning turns
# and tool calls are counted separately: sharing one counter means every extra search costs a
# reasoning turn, so the deepest research turns end up with the least room to synthesise.

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MAX_LLM_TURNS = 6
DEFAULT_MAX_TOOL_CALLS = 6
MAX_LLM_TURNS_LIMIT = 10
MAX_TOOL_CALLS_LIMIT = 10


def _get_clamped_int_env(name: str, default: int, *, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return min(max(value, 1), maximum)


def _legacy_total_steps() -> int | None:
    """Read the superseded combined budget so existing deployments keep their intent."""
    raw = os.environ.get("CHAT_AGENT_MAX_STEPS")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def get_max_tool_calls() -> int:
    explicit = os.environ.get("CHAT_AGENT_MAX_TOOL_CALLS")
    if explicit is not None:
        return _get_clamped_int_env(
            "CHAT_AGENT_MAX_TOOL_CALLS",
            DEFAULT_MAX_TOOL_CALLS,
            maximum=MAX_TOOL_CALLS_LIMIT,
        )
    legacy_total = _legacy_total_steps()
    if legacy_total is not None:
        return min(max(legacy_total // 2, 1), MAX_TOOL_CALLS_LIMIT)
    return DEFAULT_MAX_TOOL_CALLS


def get_max_llm_turns() -> int:
    explicit = os.environ.get("CHAT_AGENT_MAX_LLM_TURNS")
    if explicit is not None:
        return _get_clamped_int_env(
            "CHAT_AGENT_MAX_LLM_TURNS",
            DEFAULT_MAX_LLM_TURNS,
            maximum=MAX_LLM_TURNS_LIMIT,
        )
    legacy_total = _legacy_total_steps()
    if legacy_total is not None:
        return min(max(legacy_total - (legacy_total // 2), 1), MAX_LLM_TURNS_LIMIT)
    return DEFAULT_MAX_LLM_TURNS


@dataclass
class AgentStepBudget:
    """Mutable per-turn step accounting shared by the loop and its tool runners."""

    max_llm_turns: int
    max_tool_calls: int
    llm_turns: int = 0
    tool_calls: int = 0

    @classmethod
    def from_environment(cls) -> "AgentStepBudget":
        return cls(
            max_llm_turns=get_max_llm_turns(),
            max_tool_calls=get_max_tool_calls(),
        )

    @property
    def max_steps(self) -> int:
        """Displayed total, kept as the sum so progress events stay meaningful."""
        return self.max_llm_turns + self.max_tool_calls

    @property
    def step(self) -> int:
        return self.llm_turns + self.tool_calls

    @property
    def tool_calls_exhausted(self) -> bool:
        return self.tool_calls >= self.max_tool_calls

    @property
    def llm_turns_exhausted(self) -> bool:
        return self.llm_turns >= self.max_llm_turns

    @property
    def research_exhausted(self) -> bool:
        return self.tool_calls_exhausted or self.llm_turns_exhausted

    def start_llm_turn(self) -> int:
        self.llm_turns += 1
        return self.step

    def start_tool_call(self) -> int:
        self.tool_calls += 1
        return self.step
