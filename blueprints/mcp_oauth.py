"""Browser-facing consent and connection-management APIs for remote MCP OAuth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from services.async_utils import run_blocking
from services.csrf import require_csrf
from services.mcp_config import is_mcp_enabled
from services.mcp_oauth import (
    ClientLimitReachedError,
    InvalidRedirectUriError,
    complete_consent,
    consent_details,
    issue_user_client,
    list_connections,
    list_user_clients,
    revoke_connection,
    revoke_user_client,
    update_connection_display_name,
    update_user_client_label,
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


@mcp_oauth_bp.get("/clients", name="mcp_oauth.list_clients")
async def get_clients(request: Request):
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    return jsonify(await run_blocking(list_user_clients, user_id))


@mcp_oauth_bp.post("/clients", name="mcp_oauth.issue_client")
async def post_client(request: Request):
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    body, error = await require_json_dict(request)
    if error is not None:
        return error
    label = body.get("label") if body else None
    redirect_uri = body.get("redirect_uri") if body else None
    if label is not None and not isinstance(label, str):
        return jsonify({"error": "認証情報の名前が不正です。"}, status_code=400)
    if redirect_uri is not None and not isinstance(redirect_uri, str):
        return jsonify({"error": "コールバックURL（リダイレクトURI）が不正です。"}, status_code=400)
    try:
        credentials = await run_blocking(issue_user_client, user_id, label, redirect_uri)
    except InvalidRedirectUriError:
        return jsonify({"error": "コールバックURL（リダイレクトURI）が不正です。"}, status_code=400)
    except ValueError:
        return jsonify({"error": "メールアドレスの確認後に連携用認証情報を発行できます。"}, status_code=403)
    except ClientLimitReachedError:
        return jsonify({"error": "保存できる認証情報の上限に達しました。不要な認証情報を削除してください。"}, status_code=409)
    return jsonify(credentials, status_code=201)


@mcp_oauth_bp.delete("/clients/{client_id}", name="mcp_oauth.revoke_client")
async def delete_client(client_id: str, request: Request):
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    revoked = await run_blocking(revoke_user_client, user_id, client_id)
    if not revoked:
        return jsonify({"error": "対象の認証情報が見つかりません。"}, status_code=404)
    return jsonify({"message": "認証情報を削除しました。"})


@mcp_oauth_bp.patch("/clients/{client_id}", name="mcp_oauth.update_client_label")
async def patch_client(client_id: str, request: Request):
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    body, error = await require_json_dict(request)
    if error is not None:
        return error
    label = body.get("label") if body else None
    if not isinstance(label, str):
        return jsonify({"error": "認証情報の名前が不正です。"}, status_code=400)
    updated = await run_blocking(update_user_client_label, user_id, client_id, label)
    if not updated:
        return jsonify({"error": "対象の認証情報が見つかりません。"}, status_code=404)
    return jsonify({"message": "認証情報の名前を更新しました。"})


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


@mcp_oauth_bp.patch("/connections/{grant_id}", name="mcp_oauth.update_connection_display_name")
async def patch_connection(grant_id: str, request: Request):
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    body, error = await require_json_dict(request)
    if error is not None:
        return error
    display_name = body.get("display_name") if body else None
    if not isinstance(display_name, str):
        return jsonify({"error": "AIサービスの表示名が不正です。"}, status_code=400)
    updated = await run_blocking(update_connection_display_name, user_id, grant_id, display_name)
    if not updated:
        return jsonify({"error": "対象の連携が見つかりません。"}, status_code=404)
    return jsonify({"message": "AIサービスの表示名を更新しました。"})
