"""MCP ツール共通の、認可（scope 検査）・必要 scope の対応表・レート制限・監査ログのヘルパー。

`mcp_server.py` と `mcp_tools/` の各ツールが、実行ユーザーの特定と権限確認、操作回数の制限に使う。
Shared MCP tool authorization, scope metadata, rate-limit and audit-log helpers.
Used by `mcp_server.py` and the tools under `mcp_tools/` to identify the caller, check permission and limit operation counts.
"""

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


# ツール名ごとに必要な OAuth scope。ここに無いツールは一覧取得時に登録漏れとして例外になる（ChatCoreFastMCP.list_tools）。
# OAuth scope required per tool name; a tool missing here raises as a registration bug when tools are listed (ChatCoreFastMCP.list_tools).
TOOL_REQUIRED_SCOPES: dict[str, str] = {
    "publish_prompt": MCP_PROMPTS_WRITE_SCOPE,
    "publish_image_prompt": MCP_PROMPTS_WRITE_SCOPE,
    "publish_image_prompt_base64": MCP_PROMPTS_WRITE_SCOPE,
    "start_image_prompt_upload": MCP_PROMPTS_WRITE_SCOPE,
    "append_image_prompt_upload": MCP_PROMPTS_WRITE_SCOPE,
    "cancel_image_prompt_upload": MCP_PROMPTS_WRITE_SCOPE,
    "publish_chunked_image_prompt": MCP_PROMPTS_WRITE_SCOPE,
    "publish_skill": MCP_PROMPTS_WRITE_SCOPE,
    "list_shared_content": MCP_PROMPTS_READ_SCOPE,
    "search_shared_content": MCP_PROMPTS_READ_SCOPE,
    "get_shared_content": MCP_PROMPTS_READ_SCOPE,
    "list_skill_resources": MCP_PROMPTS_READ_SCOPE,
    "get_skill_resource": MCP_PROMPTS_READ_SCOPE,
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
    """1回の MCP ツール呼び出しを行う、認証済みの Chat-Core ユーザーと OAuth クライアント。

    Authenticated Chat-Core user and OAuth client invoking one MCP tool.
    """

    user_id: int
    client_id: str


def require_actor(required_scope: str) -> McpActor:
    """認証済みユーザーを特定し、ツールに必要な OAuth scope を持つか検査する。

    Resolve the authenticated user and enforce the tool's OAuth scope.
    """
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
    """MCP の操作群に対して、ユーザーとクライアントの組ごとの回数制限をかける。

    Apply a per-user and per-client limit to an MCP operation family.
    """
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
    """MCP で書き込み系の操作が成功したことを、内容を含まない監査イベントとして記録する。

    Record a content-free audit event for a successful MCP mutation.
    """
    audit_logger.info(
        "MCP mutation succeeded",
        extra={
            "mcp_tool": tool_name,
            "mcp_user_id": actor.user_id,
            "mcp_client_id": actor.client_id,
            "mcp_target_id": target_id,
        },
    )
