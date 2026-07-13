"""Browser-facing consent and connection-management APIs for remote MCP OAuth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from services.async_utils import run_blocking
from services.csrf import require_csrf
from services.mcp_config import is_mcp_enabled
from services.mcp_oauth import (
    complete_consent,
    consent_details,
    get_claude_client_status,
    issue_claude_client,
    list_connections,
    revoke_connection,
)
from services.web import jsonify, require_json_dict

mcp_oauth_bp = APIRouter(prefix="/api/mcp/oauth", dependencies=[Depends(require_csrf)])


def _current_verified_user_id(request: Request) -> int | None:
    user_id = request.session.get("user_id")
    return int(user_id) if isinstance(user_id, int) and user_id > 0 else None


def _disabled_response():
    return jsonify({"error": "MCP連携は現在有効ではありません。"}, status_code=404)


@mcp_oauth_bp.get("/consent", name="mcp_oauth.consent_details")
async def get_consent_details(request: Request):
    if not is_mcp_enabled():
        return _disabled_response()
    if _current_verified_user_id(request) is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    token = request.query_params.get("request", "")
    details = await run_blocking(consent_details, token)
    if not details:
        return jsonify({"error": "認可リクエストが無効または期限切れです。"}, status_code=400)
    return jsonify(details)


@mcp_oauth_bp.post("/consent", name="mcp_oauth.complete_consent")
async def post_consent(request: Request):
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    body, error = await require_json_dict(request)
    if error is not None:
        return error
    token = body.get("request") if body else None
    decision = body.get("decision") if body else None
    if not isinstance(token, str) or decision not in {"approve", "deny"}:
        return jsonify({"error": "認可リクエストが不正です。"}, status_code=400)
    redirect_url = await run_blocking(complete_consent, token, user_id, decision == "approve")
    if not redirect_url:
        return jsonify({"error": "認可リクエストが無効、期限切れ、または利用できません。"}, status_code=400)
    return jsonify({"redirect_url": redirect_url})


@mcp_oauth_bp.get("/connections", name="mcp_oauth.list_connections")
async def get_connections(request: Request):
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    connections = await run_blocking(list_connections, user_id)
    return jsonify({"connections": connections})


@mcp_oauth_bp.get("/claude-client", name="mcp_oauth.claude_client_status")
async def get_claude_client(request: Request):
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    return jsonify(await run_blocking(get_claude_client_status, user_id))


@mcp_oauth_bp.post("/claude-client", name="mcp_oauth.issue_claude_client")
async def post_claude_client(request: Request):
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    try:
        credentials = await run_blocking(issue_claude_client, user_id)
    except ValueError:
        return jsonify({"error": "メールアドレスの確認後に連携用認証情報を発行できます。"}, status_code=403)
    return jsonify(credentials, status_code=201)


@mcp_oauth_bp.delete("/connections/{grant_id}", name="mcp_oauth.revoke_connection")
async def delete_connection(grant_id: str, request: Request):
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    revoked = await run_blocking(revoke_connection, user_id, grant_id)
    if not revoked:
        return jsonify({"error": "対象の連携が見つかりません。"}, status_code=404)
    return jsonify({"message": "AIサービス連携を解除しました。"})
