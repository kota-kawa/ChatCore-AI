"""Rate limits for creating a public shared prompt, shared by the Web composer and chat.

Web の投稿フォーム（blueprints/prompt_share/prompt_share_api.py）とチャットの承認 API
（publish_prompt の承認実行）は、同じキー・同じ上限（8件/ユーザー/時、12件/IP/時、
ユーザー別15秒クールダウン）でこの投稿レートを消費する。チャットからの承認には、
これとは別にチャット書込み全体の上限（services/chat_tool_approval_service.py の
CHAT_TOOL_WRITE_PER_HOUR）が重ねて掛かる。MCP経由の投稿は別の上限（services/mcp_config.py）
を使い、ここには影響しない。

Both the Web composer form (blueprints/prompt_share/prompt_share_api.py) and the chat approval
API (running an approved publish_prompt) consume this same posting rate through the same keys
and limits (8 per user per hour, 12 per IP per hour, a 15-second per-user cooldown). A chat
approval additionally spends the general chat-write budget
(CHAT_TOOL_WRITE_PER_HOUR in services/chat_tool_approval_service.py). Posts made through MCP use
a separate limit (services/mcp_config.py) untouched by this module.
"""

from __future__ import annotations

from services.auth_limits import consume_rate_limit
from services.error_messages import ERROR_PROMPT_CREATE_RATE_LIMITED_TEMPLATE

PROMPT_CREATE_RATE_WINDOW_SECONDS = 60 * 60
PROMPT_CREATE_PER_IP_LIMIT = 12
PROMPT_CREATE_PER_USER_LIMIT = 8
PROMPT_CREATE_COOLDOWN_SECONDS = 15


# IP が分からない呼び出し元（想定外の経路）では IP 単位の上限だけ省き、ユーザー単位の上限と
# クールダウンは必ず適用する。
# A caller without a known IP (an unexpected path) skips only the per-IP check; the per-user
# limit and cooldown always apply.
def consume_prompt_create_limits(
    client_ip: str | None,
    user_id: int,
) -> tuple[bool, str | None, int | None]:
    checks: list[tuple[str, str, int, int]] = []
    if client_ip:
        checks.append(("prompt:create:ip", client_ip, PROMPT_CREATE_PER_IP_LIMIT, PROMPT_CREATE_RATE_WINDOW_SECONDS))
    checks.append(("prompt:create:user", str(user_id), PROMPT_CREATE_PER_USER_LIMIT, PROMPT_CREATE_RATE_WINDOW_SECONDS))
    checks.append(("prompt:create:cooldown", str(user_id), 1, PROMPT_CREATE_COOLDOWN_SECONDS))
    for key_prefix, identifier, limit, window_seconds in checks:
        allowed, _, retry_after = consume_rate_limit(
            key_prefix,
            identifier,
            limit=limit,
            window_seconds=window_seconds,
        )
        if not allowed:
            return (
                False,
                ERROR_PROMPT_CREATE_RATE_LIMITED_TEMPLATE.format(seconds=retry_after),
                retry_after,
            )
    return True, None, None
