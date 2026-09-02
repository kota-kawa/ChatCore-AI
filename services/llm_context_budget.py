"""LLM request context-window accounting.

The chat agent can make several model calls during one turn.  A provider's
context limit applies to each individual request, including the output budget
and the tool definitions, so counting only the visible message text is not
enough.  This module keeps that accounting independent from the provider
clients and can therefore be used before any request is sent.

The values below are application configuration rather than a claim about a
provider's current API limits.  They are deliberately conservative and can be
overridden with environment variables when a deployment has a different
contract.  Only ``os.environ`` is consulted; this module never loads ``.env``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from services.chat_context import estimate_token_count
from services.llm_model_limits import (
    MODEL_MAX_OUTPUT_TOKENS,
    QWEN_3_6_27B_MAX_OUTPUT_TOKENS,
    QWEN_3_6_27B_MODEL,
    get_model_max_output_tokens,
)

# The supported model names are repeated here intentionally.  Importing these
# constants from services.llm would create an import cycle once the LLM layer
# uses this module for its preflight check.
GPT_OSS_120B_MODEL = "openai/gpt-oss-120b"
GPT_OSS_20B_MODEL = "openai/gpt-oss-20b"
GPT_5_6_LUNA_MODEL = "gpt-5.6-luna"
CLAUDE_HAIKU_4_5_MODEL = "claude-haiku-4-5-20251001"

# Known windows are kept per model so a deployment can safely run different
# providers in the same process.  The fallback is substantially smaller than
# these values: an unrecognised model must never cause an optimistic request.
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    GPT_OSS_120B_MODEL: 131_072,
    GPT_OSS_20B_MODEL: 131_072,
    QWEN_3_6_27B_MODEL: 131_072,
    GPT_5_6_LUNA_MODEL: 128_000,
    CLAUDE_HAIKU_4_5_MODEL: 200_000,
}
DEFAULT_CONTEXT_WINDOW_TOKENS = 65_536
UNKNOWN_MODEL_CONTEXT_WINDOW_TOKENS = DEFAULT_CONTEXT_WINDOW_TOKENS

# These defaults mirror the phase budgets in services.llm without importing
# that provider module.  The values are read at call time, so a test or a
# long-running deployment can change its configuration without reloading this
# module.
DEFAULT_OUTPUT_TOKENS = 16_384
DEFAULT_ANSWER_OUTPUT_TOKENS = 32_768

# Reserve room for provider-side tokenization differences and request framing.
# The margin is intentionally independent of the input text estimate.
DEFAULT_SAFETY_MARGIN_TOKENS = 2_048

# Tool schema JSON is counted directly and each definition receives a small
# framing allowance.  The framing allowance can be tuned without changing the
# estimator's semantic behavior.
DEFAULT_TOOL_DEFINITION_OVERHEAD_TOKENS = 64
MESSAGE_FRAME_OVERHEAD_TOKENS = 4

# 通常チャットの検索判断と回答は単一の agent フェーズで実行する。調査専用フェーズは無い。
# Search decisions and answers share one agent phase in normal chat; no research-only phase.
ANSWER_GENERATION_PHASES = frozenset(
    {"agent", "final_answer", "continuation", "final_answer_deep", "continuation_deep"}
)


def _positive_int(value: Any, default: int) -> int:
    """Return a positive integer or ``default`` for malformed values."""

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _non_negative_int(value: Any, default: int) -> int:
    """Return a non-negative integer or ``default`` for malformed values."""

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _positive_int_env(name: str, default: int) -> int:
    return _positive_int(os.environ.get(name), default)


def _non_negative_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return _non_negative_int(raw, default)


def _model_env_suffix(model_name: str) -> str:
    """Convert a model name into a safe, readable environment suffix."""

    return "".join(character if character.isalnum() else "_" for character in model_name.upper()).strip(
        "_"
    )


def get_model_context_window(model_name: str | None) -> int:
    """Return the configured context window for ``model_name``.

    A model-specific override (``LLM_CONTEXT_WINDOW_<MODEL>``) wins over the
    global override.  Unknown and empty model names use the conservative
    fallback rather than assuming the largest supported window.
    """

    normalized_name = str(model_name or "").strip()
    if normalized_name:
        suffix = _model_env_suffix(normalized_name)
        if suffix:
            specific_name = f"LLM_CONTEXT_WINDOW_{suffix}"
            specific = os.environ.get(specific_name)
            if specific is not None:
                return _positive_int(specific, MODEL_CONTEXT_WINDOWS.get(normalized_name, UNKNOWN_MODEL_CONTEXT_WINDOW_TOKENS))

    global_override = os.environ.get("LLM_CONTEXT_WINDOW_TOKENS")
    if global_override is not None:
        return _positive_int(global_override, MODEL_CONTEXT_WINDOWS.get(normalized_name, UNKNOWN_MODEL_CONTEXT_WINDOW_TOKENS))

    return MODEL_CONTEXT_WINDOWS.get(normalized_name, UNKNOWN_MODEL_CONTEXT_WINDOW_TOKENS)


def get_output_reserved_tokens(
    generation_phase: str = "default",
    model_name: str | None = None,
) -> int:
    """Return the output tokens reserved for a generation phase.

    This follows the same environment variables as ``services.llm``.  Unknown
    phases intentionally use the general output cap rather than the larger
    answer cap. A known provider cap is applied so the preflight reflects the
    maximum the provider will accept.
    """

    phase = str(generation_phase or "default").strip().lower()
    configured = (
        _positive_int_env("LLM_MAX_TOKENS_ANSWER", DEFAULT_ANSWER_OUTPUT_TOKENS)
        if phase in ANSWER_GENERATION_PHASES
        else _positive_int_env("LLM_MAX_TOKENS", DEFAULT_OUTPUT_TOKENS)
    )
    provider_limit = get_model_max_output_tokens(model_name)
    return min(configured, provider_limit) if provider_limit is not None else configured


def get_safety_margin_tokens() -> int:
    """Return the configured safety margin for provider-side accounting drift."""

    return _non_negative_int_env(
        "LLM_CONTEXT_SAFETY_MARGIN_TOKENS",
        DEFAULT_SAFETY_MARGIN_TOKENS,
    )


def get_tool_definition_overhead_tokens() -> int:
    """Return the per-tool schema framing allowance."""

    return _non_negative_int_env(
        "LLM_TOOL_SCHEMA_OVERHEAD_TOKENS",
        DEFAULT_TOOL_DEFINITION_OVERHEAD_TOKENS,
    )


def _serialize_for_estimation(value: Any) -> str:
    """Serialize an SDK-shaped value without allowing estimation to fail.

    Provider payloads are normally JSON-compatible dictionaries.  ``default``
    handles lightweight SDK objects and test doubles while keeping estimation
    deterministic for ordinary payloads.
    """

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    except (TypeError, ValueError, OverflowError):
        return str(value)


def estimate_messages_tokens(messages: Sequence[Mapping[str, Any]] | None) -> int:
    """Estimate all message fields, including tool calls and metadata.

    Estimating the complete serialized message catches ``role``, ``name``,
    ``tool_call_id``, multimodal content blocks, and assistant ``tool_calls``;
    counting only ``content`` would under-budget exactly the requests that grow
    during a tool loop.  A small per-message framing allowance covers provider
    separators that are not represented in the JSON payload.
    """

    if not messages:
        return 0

    total = 0
    for message in messages:
        serialized = _serialize_for_estimation(message)
        total += estimate_token_count(serialized) + MESSAGE_FRAME_OVERHEAD_TOKENS
    return total


def estimate_tools_tokens(tools: Sequence[Mapping[str, Any]] | None) -> int:
    """Estimate tool schemas plus per-definition/provider framing overhead."""

    if not tools:
        return 0

    # Materialize once so generators and other one-shot sequences are handled
    # consistently by both the JSON estimator and the count below.
    tool_list = list(tools)
    if not tool_list:
        return 0
    serialized = _serialize_for_estimation({"tools": tool_list})
    return estimate_token_count(serialized) + (
        len(tool_list) * get_tool_definition_overhead_tokens()
    )


def estimate_request_tokens(
    messages: Sequence[Mapping[str, Any]] | None,
    tools: Sequence[Mapping[str, Any]] | None = None,
) -> int:
    """Estimate the complete input portion of a provider request."""

    return estimate_messages_tokens(messages) + estimate_tools_tokens(tools)


@dataclass(frozen=True, slots=True)
class LlmContextBudget:
    """The effective token budget for one model/phase request.

    ``available_input_tokens`` is the amount available to serialized messages;
    tool schema tokens, output reservation, and the safety margin are already
    removed.  ``estimate_request_tokens`` should be compared with
    ``context_window_tokens - output_reserved_tokens - safety_margin_tokens``
    when tools are present, or callers can use ``fits``/``request_fits_context``
    to avoid duplicating that arithmetic.
    """

    model_name: str
    generation_phase: str
    context_window_tokens: int
    output_reserved_tokens: int
    tool_schema_tokens: int
    safety_margin_tokens: int

    @property
    def reserved_tokens(self) -> int:
        """Tokens unavailable to message content in this request."""

        return (
            self.output_reserved_tokens
            + self.tool_schema_tokens
            + self.safety_margin_tokens
        )

    @property
    def available_input_tokens(self) -> int:
        """Return the non-negative message-token allowance."""

        return max(self.context_window_tokens - self.reserved_tokens, 0)

    @property
    def total_reserved_tokens(self) -> int:
        """Backward-friendly alias for ``reserved_tokens``."""

        return self.reserved_tokens

    def fits_message_tokens(self, message_tokens: int) -> bool:
        """Return whether a message-only estimate fits this budget."""

        return _non_negative_int(message_tokens, 0) <= self.available_input_tokens


def get_context_budget(
    model_name: str,
    generation_phase: str = "default",
    tools: Sequence[Mapping[str, Any]] | None = None,
    *,
    output_reserved_tokens: int | None = None,
    safety_margin_tokens: int | None = None,
    tool_schema_tokens: int | None = None,
) -> LlmContextBudget:
    """Build a context budget for a model and generation phase.

    Optional overrides are useful when a provider reports a request-specific
    output cap.  By default all values are resolved from the model table,
    phase, environment, and actual tool definitions.
    """

    normalized_name = str(model_name or "").strip()
    phase = str(generation_phase or "default").strip().lower() or "default"
    default_output = get_output_reserved_tokens(phase, normalized_name)
    resolved_output = (
        default_output
        if output_reserved_tokens is None
        else _positive_int(output_reserved_tokens, default_output)
    )
    provider_limit = get_model_max_output_tokens(normalized_name)
    if provider_limit is not None:
        resolved_output = min(resolved_output, provider_limit)
    resolved_safety = (
        get_safety_margin_tokens()
        if safety_margin_tokens is None
        else _non_negative_int(safety_margin_tokens, get_safety_margin_tokens())
    )
    resolved_tool_schema = (
        estimate_tools_tokens(tools)
        if tool_schema_tokens is None
        else _non_negative_int(tool_schema_tokens, estimate_tools_tokens(tools))
    )
    return LlmContextBudget(
        model_name=normalized_name,
        generation_phase=phase,
        context_window_tokens=get_model_context_window(normalized_name),
        output_reserved_tokens=resolved_output,
        tool_schema_tokens=resolved_tool_schema,
        safety_margin_tokens=resolved_safety,
    )


def get_available_input_tokens(
    model_name: str,
    generation_phase: str = "default",
    tools: Sequence[Mapping[str, Any]] | None = None,
    *,
    output_reserved_tokens: int | None = None,
    safety_margin_tokens: int | None = None,
    tool_schema_tokens: int | None = None,
) -> int:
    """Return the available message-token allowance for one request."""

    return get_context_budget(
        model_name,
        generation_phase,
        tools,
        output_reserved_tokens=output_reserved_tokens,
        safety_margin_tokens=safety_margin_tokens,
        tool_schema_tokens=tool_schema_tokens,
    ).available_input_tokens


def request_fits_context(
    messages: Sequence[Mapping[str, Any]] | None,
    model_name: str,
    generation_phase: str = "default",
    tools: Sequence[Mapping[str, Any]] | None = None,
    *,
    output_reserved_tokens: int | None = None,
    safety_margin_tokens: int | None = None,
    tool_schema_tokens: int | None = None,
) -> bool:
    """Check a complete request against its effective context budget."""

    budget = get_context_budget(
        model_name,
        generation_phase,
        tools,
        output_reserved_tokens=output_reserved_tokens,
        safety_margin_tokens=safety_margin_tokens,
        tool_schema_tokens=tool_schema_tokens,
    )
    message_tokens = estimate_messages_tokens(messages)
    return message_tokens <= budget.available_input_tokens


# Explicit aliases keep call sites readable while allowing future integrations
# to use terminology from the planning document.
get_llm_context_budget = get_context_budget
calculate_available_input_tokens = get_available_input_tokens
estimate_messages_and_tools_tokens = estimate_request_tokens
is_request_within_budget = request_fits_context


__all__ = [
    "ANSWER_GENERATION_PHASES",
    "CLAUDE_HAIKU_4_5_MODEL",
    "DEFAULT_CONTEXT_WINDOW_TOKENS",
    "DEFAULT_OUTPUT_TOKENS",
    "DEFAULT_SAFETY_MARGIN_TOKENS",
    "GPT_5_6_LUNA_MODEL",
    "GPT_OSS_120B_MODEL",
    "GPT_OSS_20B_MODEL",
    "LlmContextBudget",
    "MODEL_CONTEXT_WINDOWS",
    "MODEL_MAX_OUTPUT_TOKENS",
    "QWEN_3_6_27B_MAX_OUTPUT_TOKENS",
    "QWEN_3_6_27B_MODEL",
    "calculate_available_input_tokens",
    "estimate_messages_and_tools_tokens",
    "estimate_messages_tokens",
    "estimate_request_tokens",
    "estimate_tools_tokens",
    "get_available_input_tokens",
    "get_context_budget",
    "get_llm_context_budget",
    "get_model_context_window",
    "get_model_max_output_tokens",
    "get_output_reserved_tokens",
    "get_safety_margin_tokens",
    "get_tool_definition_overhead_tokens",
    "is_request_within_budget",
    "request_fits_context",
]
