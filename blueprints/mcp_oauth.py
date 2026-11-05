"""リモート MCP の OAuth について、ブラウザ（フロントエンド）から呼ばれる同意・接続管理 API。

Browser-facing consent and connection-management APIs for remote MCP OAuth.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from services.csrf import require_csrf
from services.mcp_config import is_mcp_enabled
from services.mcp_oauth import (
    MCP_ALLOWED_SCOPES,
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

# CSRF保護付きのリモートMCP向けOAuth同意・接続管理ルーター。
# Router for remote MCP OAuth consent and connection management, with CSRF protection.
mcp_oauth_bp = APIRouter(prefix="/api/mcp/oauth", dependencies=[Depends(require_csrf)])


def _current_verified_user_id(request: Request) -> int | None:
    # セッションの user_id が正の整数のときだけユーザーIDとして扱い、それ以外は未ログイン（None）とみなす。
    # Treat the session user_id as valid only when it is a positive int; anything else counts as not logged in (None).
    user_id = request.session.get("user_id")
    return int(user_id) if isinstance(user_id, int) and user_id > 0 else None


def _disabled_response():
    # MCP連携が無効な環境では、存在自体を隠すため全エンドポイントで 404 を返す。
    # When MCP is disabled, every endpoint returns 404 so the feature appears not to exist.
    return jsonify({"error": "MCP連携は現在有効ではありません。"}, status_code=404)


@mcp_oauth_bp.get("/consent", name="mcp_oauth.consent_details")
async def get_consent_details(request: Request):
    """同意画面に表示する、認可リクエスト（トークン）の内容を返す。

    Return the details of an authorization request (by token) for the consent screen.
    """
    if not is_mcp_enabled():
        return _disabled_response()
    if _current_verified_user_id(request) is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    token = request.query_params.get("request", "")
    details = consent_details(token)
    if not details:
        return jsonify({"error": "認可リクエストが無効または期限切れです。"}, status_code=400)
    return jsonify(details)


@mcp_oauth_bp.post("/consent", name="mcp_oauth.complete_consent")
async def post_consent(request: Request):
    """同意画面での承認・拒否を確定し、クライアントへ戻すリダイレクトURLを返す。

    Record the approve/deny decision from the consent screen and return the redirect URL back to the client.
    """
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
    redirect_url = await complete_consent(token, user_id, decision == "approve")
    if not redirect_url:
        return jsonify({"error": "認可リクエストが無効、期限切れ、または利用できません。"}, status_code=400)
    return jsonify({"redirect_url": redirect_url})


@mcp_oauth_bp.get("/connections", name="mcp_oauth.list_connections")
async def get_connections(request: Request):
    """ユーザーが許可済みの AI サービス連携（グラント）の一覧を返す。

    List the AI-service connections (grants) the user has authorized.
    """
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    connections = await list_connections(user_id)
    return jsonify({"connections": connections})


@mcp_oauth_bp.get("/clients", name="mcp_oauth.list_clients")
async def get_clients(request: Request):
    """ユーザーが発行した連携用の OAuth クライアント認証情報の一覧を返す。

    List the OAuth client credentials the user has issued for integrations.
    """
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    return jsonify(await list_user_clients(user_id))


@mcp_oauth_bp.post("/clients", name="mcp_oauth.issue_client")
async def post_client(request: Request):
    """連携用の OAuth クライアント認証情報を発行する。入力型とスコープを検証し、サービス層の例外を HTTP ステータスへ対応づける。

    Issue OAuth client credentials for an integration. Validates input types and scopes, and maps service-layer errors to HTTP statuses.
    """
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
    issue_client_secret = body.get("issue_client_secret", True) if body else True
    scopes = body.get("scopes") if body else None
    if label is not None and not isinstance(label, str):
        return jsonify({"error": "認証情報の名前が不正です。"}, status_code=400)
    if redirect_uri is not None and not isinstance(redirect_uri, str):
        return jsonify({"error": "コールバックURL（リダイレクトURI）が不正です。"}, status_code=400)
    if not isinstance(issue_client_secret, bool):
        return jsonify({"error": "OAuthクライアントシークレットの設定が不正です。"}, status_code=400)
    if scopes is not None and (
        not isinstance(scopes, list)
        or not scopes
        or any(not isinstance(scope, str) or scope not in MCP_ALLOWED_SCOPES for scope in scopes)
    ):
        return jsonify({"error": "OAuthスコープの指定が不正です。"}, status_code=400)
    try:
        credentials = await issue_user_client(
            user_id,
            label,
            redirect_uri,
            issue_client_secret,
            scopes,
        )
    except InvalidRedirectUriError:
        return jsonify({"error": "コールバックURL（リダイレクトURI）が不正です。"}, status_code=400)
    except ValueError:
        return jsonify({"error": "メールアドレスの確認後に連携用認証情報を発行できます。"}, status_code=403)
    except ClientLimitReachedError:
        return jsonify({"error": "保存できる認証情報の上限に達しました。不要な認証情報を削除してください。"}, status_code=409)
    return jsonify(credentials, status_code=201)


@mcp_oauth_bp.delete("/clients/{client_id}", name="mcp_oauth.revoke_client")
async def delete_client(client_id: str, request: Request):
    """指定した OAuth クライアント認証情報を削除（失効）する。

    Delete (revoke) the specified OAuth client credentials.
    """
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    revoked = await revoke_user_client(user_id, client_id)
    if not revoked:
        return jsonify({"error": "対象の認証情報が見つかりません。"}, status_code=404)
    return jsonify({"message": "認証情報を削除しました。"})


@mcp_oauth_bp.patch("/clients/{client_id}", name="mcp_oauth.update_client_label")
async def patch_client(client_id: str, request: Request):
    """OAuth クライアント認証情報の名前（ラベル）を更新する。

    Update the label of the specified OAuth client credentials.
    """
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
    updated = await update_user_client_label(user_id, client_id, label)
    if not updated:
        return jsonify({"error": "対象の認証情報が見つかりません。"}, status_code=404)
    return jsonify({"message": "認証情報の名前を更新しました。"})


@mcp_oauth_bp.delete("/connections/{grant_id}", name="mcp_oauth.revoke_connection")
async def delete_connection(grant_id: str, request: Request):
    """指定した AI サービス連携（グラント）を解除する。

    Revoke the specified AI-service connection (grant).
    """
    if not is_mcp_enabled():
        return _disabled_response()
    user_id = _current_verified_user_id(request)
    if user_id is None:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    revoked = await revoke_connection(user_id, grant_id)
    if not revoked:
        return jsonify({"error": "対象の連携が見つかりません。"}, status_code=404)
    return jsonify({"message": "AIサービス連携を解除しました。"})


@mcp_oauth_bp.patch("/connections/{grant_id}", name="mcp_oauth.update_connection_display_name")
async def patch_connection(grant_id: str, request: Request):
    """AI サービス連携の表示名を更新する。

    Update the display name of the specified AI-service connection.
    """
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
    updated = await update_connection_display_name(user_id, grant_id, display_name)
    if not updated:
        return jsonify({"error": "対象の連携が見つかりません。"}, status_code=404)
    return jsonify({"message": "AIサービスの表示名を更新しました。"})
