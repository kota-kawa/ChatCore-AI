"""Bounded conversation context for retrying a rejected model request."""

from typing import Any

from services.chat_context import estimate_token_count, trim_text_to_token_budget
from services.research_state import TURN_STATE_MARKER, is_reference_context_message

RECOVERY_HISTORY_TOKEN_BUDGET = 1500


def build_recovery_base_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Keep base guidance, the preceding exchange, and the latest user input.

    Reserve a share for each prior message so a long assistant response cannot
    erase its user question. Tool traffic and optional system blocks are omitted;
    the caller projects the complete TurnState and checks the full request budget.
    """
    base: list[dict[str, str]] = []
    first_system = next(
        (
            message for message in messages
            if message.get("role") == "system"
            and not str(message.get("content") or "").lstrip().startswith(TURN_STATE_MARKER)
            and not is_reference_context_message(message)
        ),
        None,
    )
    if first_system is not None:
        base.append({
            "role": "system",
            "content": trim_text_to_token_budget(str(first_system.get("content") or ""), 3000),
        })

    conversation = [
        {"role": str(message["role"]), "content": str(message.get("content") or "")}
        for message in messages
        if message.get("role") in {"user", "assistant"}
        and not message.get("tool_calls")
        and str(message.get("content") or "").strip()
    ]
    latest_user_index = next(
        (index for index in range(len(conversation) - 1, -1, -1)
         if conversation[index]["role"] == "user"),
        None,
    )
    if latest_user_index is None:
        return base

    previous = conversation[max(0, latest_user_index - 2):latest_user_index]
    remaining = RECOVERY_HISTORY_TOKEN_BUDGET
    for index, message in enumerate(previous):
        content = trim_text_to_token_budget(message["content"], remaining // (len(previous) - index))
        if content:
            base.append({"role": message["role"], "content": content})
            remaining -= estimate_token_count(content)
    # Preserve the user's current request verbatim, including any reference prefix.
    base.append(conversation[latest_user_index])
    return base
