"""Shared MCP tool authorization, metadata, and rate-limit helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp.exceptions import ToolError

from services.async_utils import run_blocking
from services.auth_limits import consume_rate_limit
from services.mcp_oauth import (
    MCP_CONTEXT_READ_SCOPE,
    MCP_CONTEXT_WRITE_SCOPE,
    MCP_MEMOS_READ_SCOPE,
    MCP_MEMOS_WRITE_SCOPE,
    MCP_PROMPTS_READ_SCOPE,
    MCP_PROMPTS_WRITE_SCOPE,
)

audit_logger = logging.getLogger("chat_core.mcp.audit")


TOOL_REQUIRED_SCOPES: dict[str, str] = {
    "publish_prompt": MCP_PROMPTS_WRITE_SCOPE,
    "publish_skill": MCP_PROMPTS_WRITE_SCOPE,
    "list_shared_content": MCP_PROMPTS_READ_SCOPE,
    "search_shared_content": MCP_PROMPTS_READ_SCOPE,
    "get_shared_content": MCP_PROMPTS_READ_SCOPE,
    "list_prompt_categories": MCP_PROMPTS_READ_SCOPE,
    "list_memos": MCP_MEMOS_READ_SCOPE,
    "search_memos": MCP_MEMOS_READ_SCOPE,
    "get_memo": MCP_MEMOS_READ_SCOPE,
    "list_memo_collections": MCP_MEMOS_READ_SCOPE,
    "create_memo": MCP_MEMOS_WRITE_SCOPE,
    "update_memo": MCP_MEMOS_WRITE_SCOPE,
    "append_memo_content": MCP_MEMOS_WRITE_SCOPE,
    "get_personal_context": MCP_CONTEXT_READ_SCOPE,
    "search_context": MCP_CONTEXT_READ_SCOPE,
    "save_context_fact": MCP_CONTEXT_WRITE_SCOPE,
    "update_context_fact": MCP_CONTEXT_WRITE_SCOPE,
    "deprecate_context_fact": MCP_CONTEXT_WRITE_SCOPE,
}


@dataclass(frozen=True)
class McpActor:
    """Authenticated Chat-Core user and OAuth client invoking one MCP tool."""

    user_id: int
    client_id: str


def require_actor(required_scope: str) -> McpActor:
    """Resolve the authenticated user and enforce the tool's OAuth scope."""
    token = get_access_token()
    if token is None or not token.subject:
        raise ToolError("MCPアクセストークンに認証済みユーザーがありません。")
    if required_scope not in set(token.scopes or []):
        raise ToolError(f"この操作には {required_scope} 権限が必要です。接続を再認可してください。")
    try:
        user_id = int(token.subject)
    except (TypeError, ValueError) as exc:
        raise ToolError("MCPアクセストークンのユーザー情報が不正です。") from exc
    return McpActor(user_id=user_id, client_id=str(token.client_id or "unknown"))


async def consume_tool_limit(
    actor: McpActor,
    bucket: str,
    *,
    limit: int,
    window_seconds: int,
) -> None:
    """Apply a per-user and per-client limit to an MCP operation family."""
    allowed, _, retry_after = await run_blocking(
        consume_rate_limit,
        f"mcp_tool:{bucket}",
        f"{actor.user_id}:{actor.client_id}",
        limit=limit,
        window_seconds=window_seconds,
    )
    if not allowed:
        raise ToolError(f"MCP操作の上限に達しました。約{retry_after}秒後に再試行してください。")


def audit_tool_success(actor: McpActor, tool_name: str, target_id: int | None = None) -> None:
    """Record a content-free audit event for a successful MCP mutation."""
    audit_logger.info(
        "MCP mutation succeeded",
        extra={
            "mcp_tool": tool_name,
            "mcp_user_id": actor.user_id,
            "mcp_client_id": actor.client_id,
            "mcp_target_id": target_id,
        },
    )
