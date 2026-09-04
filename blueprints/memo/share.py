from __future__ import annotations

# 共有リンクの作成・取得・更新・取り消しと、公開共有メモの取得
# Share link create / state / refresh / revoke plus the public shared-memo read

import logging

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from services.api_errors import ApiServiceError
from services.error_messages import (
    ERROR_LOGIN_REQUIRED,
    ERROR_TOKEN_REQUIRED,
)
from services.request_models import (
    MemoShareCreateRequest,
    ShareMemoRequest,
)
from services.web import (
    get_json,
    jsonify,
    jsonify_service_error,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

from services.repositories.memo_helpers import user_id_from_session

from . import memo_bp
from ._common import _memo_attr

logger = logging.getLogger(__name__)


@memo_bp.post("/api/share", name="memo.api_share")
async def api_share_memo(request: Request):
    """
    メモの共有状態を作成または取得するエンドポイント
    Endpoint to generate or get a share token/link for a memo.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.

    Returns:
        Response: 共有メタデータを含むJSONレスポンス / JSON response containing share metadata.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # JSON形式の要求を検証
    # Require JSON request format.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # リクエストデータ（対象メモID）の検証
    # Validate payload to find target memo ID.
    payload, validation_error = validate_payload_model(
        data, ShareMemoRequest, error_message="共有するメモを指定してください。", status="fail",
    )
    if validation_error is not None:
        return validation_error

    # 共有設定（強制リフレッシュフラグや有効日数）の検証
    # Validate link settings (expiration, forced refresh).
    share_options, options_error = validate_payload_model(
        data, MemoShareCreateRequest, error_message="共有リンク設定が不正です。", status="fail",
    )
    if options_error is not None:
        return options_error

    try:
        # トークンを生成または取得
        # Create or fetch shared memo token.
        share_state = await _memo_attr("create_or_get_shared_memo_token")(
            payload.memo_id,
            user_id,
            force_refresh=share_options.force_refresh,
            expires_in_days=share_options.expires_in_days,
        )
        # ペイロードをシリアライズして返却
        # Serialize the share metadata and return success.
        return jsonify(_memo_attr("_share_payload")(share_state))
    except ApiServiceError as exc:
        # メモが見つからない、または所有権が無い場合のエラーハンドリング
        # Return service error if memo does not exist or isn't owned.
        return jsonify_service_error(exc, status="fail")
    except SQLAlchemyError:
        # DBトークン作成時のエラーハンドリング
        # Handle general SQL error.
        return log_and_internal_server_error(logger, "Failed to create share link for memo entry.", status="fail")



@memo_bp.get("/api/shared", name="memo.api_shared")
async def api_shared_memo(request: Request):
    """
    共有トークンを用いて共有されたメモを一般公開用に取得するエンドポイント
    Public endpoint to retrieve a shared memo using its token.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.

    Returns:
        Response: 共有されたメモの詳細情報を含むJSONレスポンス / JSON response with shared memo details.
    """
    # クエリパラメータから共有トークンを取得
    # Get share token from query parameters.
    token = request.query_params.get("token", "").strip()
    if not token:
        return jsonify({"error": ERROR_TOKEN_REQUIRED}, status_code=400)

    try:
        # トークンによる検証とデータ取得を実行
        # Verify token validity and load shared memo details.
        payload_result = await _memo_attr("get_shared_memo_payload")(token)
        # タプル形式 (payload, status_code) で返ってきた場合は対応するステータスコードで返す
        # If payload and status code tuple returned, respond with status.
        if isinstance(payload_result, tuple) and len(payload_result) == 2:
            payload, status_code = payload_result
            return jsonify(payload, status_code=status_code)
        return jsonify(payload_result)
    except ApiServiceError as exc:
        # トークン無効化、期限切れなどのエラーを返却
        # Return service error on expired/revoked/invalid tokens.
        return jsonify_service_error(exc)
    except SQLAlchemyError:
        # 読み込み処理失敗時のエラーハンドリング
        # Respond with 500 status on database load failure.
        return log_and_internal_server_error(logger, "Failed to load shared memo payload.")



@memo_bp.get("/api/{memo_id:int}/share", name="memo.api_share_detail")
async def api_memo_share_detail(request: Request, memo_id: int):
    """
    メモの共有メタデータ詳細を取得するエンドポイント
    Endpoint to get share details for a specific memo.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        memo_id (int): メモID / The memo ID.

    Returns:
        Response: 共有メタデータを含むJSONレスポンス / JSON response containing share status.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        # 共有状態をDBから取得
        # Retrieve share status from the database.
        share_state = await _memo_attr("get_memo_share_state")(memo_id, user_id)
        # ペイロードをシリアライズして返却
        # Serialize share metadata.
        return jsonify(_memo_attr("_share_payload")(share_state))
    except ApiServiceError as exc:
        # 所有権違反や対象メモ無しのサービスエラー
        # Return service error if not authorized.
        return jsonify_service_error(exc, status="fail")
    except SQLAlchemyError:
        # DB処理エラー
        # Respond with 500 status on database query failure.
        return log_and_internal_server_error(logger, "Failed to load memo share status.", status="fail")



@memo_bp.post("/api/{memo_id:int}/share", name="memo.api_share_refresh")
async def api_memo_share_refresh(request: Request, memo_id: int):
    """
    メモの共有トークンをリフレッシュするエンドポイント
    Endpoint to refresh or recreate a memo's share token/expiration.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        memo_id (int): メモID / The memo ID.

    Returns:
        Response: 新しい共有メタデータを含むJSONレスポンス / JSON response with refreshed share details.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # リクエストデータ取得
    # Retrieve request body.
    data = await get_json(request)
    if not isinstance(data, dict):
        data = {}

    # 共有トークン設定のパラメータ検証
    # Validate the share creation options schema.
    payload, validation_error = validate_payload_model(
        data, MemoShareCreateRequest, error_message="共有リンク設定が不正です。", status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # トークンを再生成、または既存のものを取得して設定更新
        # Refresh or recreate the share token.
        share_state = await _memo_attr("create_or_get_shared_memo_token")(
            memo_id,
            user_id,
            force_refresh=payload.force_refresh,
            expires_in_days=payload.expires_in_days,
        )
        return jsonify(_memo_attr("_share_payload")(share_state))
    except ApiServiceError as exc:
        # 所有権や対象メモが見つからないエラー
        # Return service error if not authorized.
        return jsonify_service_error(exc, status="fail")
    except SQLAlchemyError:
        # DB更新エラー
        # Respond with 500 status on database write failure.
        return log_and_internal_server_error(logger, "Failed to refresh memo share status.", status="fail")



@memo_bp.post("/api/{memo_id:int}/share/revoke", name="memo.api_share_revoke")
async def api_memo_share_revoke(request: Request, memo_id: int):
    """
    メモの共有設定を無効化（トークン失効）するエンドポイント
    Endpoint to revoke the share token for a specific memo.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        memo_id (int): メモID / The memo ID.

    Returns:
        Response: 更新された共有メタデータを含むJSONレスポンス / JSON response containing revoked share status.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        # 共有トークンを無効化（無効化日時を更新）
        # Revoke the sharing token for the memo.
        share_state = await _memo_attr("revoke_shared_memo_token")(memo_id, user_id)
        return jsonify(_memo_attr("_share_payload")(share_state))
    except ApiServiceError as exc:
        # 所有権や存在確認のエラー
        # Return service error if not authorized.
        return jsonify_service_error(exc, status="fail")
    except SQLAlchemyError:
        # DB更新エラー
        # Respond with 500 status on database write failure.
        return log_and_internal_server_error(logger, "Failed to revoke memo share link.", status="fail")

