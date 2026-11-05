"""モデルに拒否されたリクエストを再試行するための、サイズを抑えた会話文脈を組み立てる。

Bounded conversation context for retrying a rejected model request.
"""

from typing import Any

from services.chat_context import estimate_token_count, trim_text_to_token_budget
from services.chat_images import IMAGE_INPUTS_KEY
from services.research_state import TURN_STATE_MARKER, is_reference_context_message

RECOVERY_HISTORY_TOKEN_BUDGET = 1500


def build_recovery_base_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """基本の指示、直前のやり取り、最新のユーザー入力だけを残す。

    過去の各メッセージに配分を確保し、長いアシスタント回答がその直前のユーザーの質問を
    押し出さないようにする。ツールのやり取りと任意の system ブロックは省く。
    完全な TurnState の投影と、リクエスト全体の予算確認は呼び出し側が行う。

    Keep base guidance, the preceding exchange, and the latest user input.

    Reserve a share for each prior message so a long assistant response cannot
    erase its user question. Tool traffic and optional system blocks are omitted;
    the caller projects the complete TurnState and checks the full request budget.
    """
    base: list[dict[str, Any]] = []
    # TurnState や参照コンテキストではない、最初の system メッセージを基本の指示として使う
    # The first system message that is neither a TurnState nor reference context serves as the base guidance
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
        {
            "role": str(message["role"]),
            "content": str(message.get("content") or ""),
            # 今回の依頼に付いた画像は、縮めた文脈でも依頼そのものの一部として残す。
            # Images on the current request remain part of the request in the reduced context.
            **({IMAGE_INPUTS_KEY: message[IMAGE_INPUTS_KEY]} if message.get(IMAGE_INPUTS_KEY) else {}),
        }
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
    # 今回のユーザー依頼は、参照の接頭辞も含めて加工せずそのまま残す。
    # Preserve the user's current request verbatim, including any reference prefix.
    base.append(conversation[latest_user_index])
    return base
