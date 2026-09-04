from __future__ import annotations

# コレクションの一覧・作成・更新・削除
# Collection list, create, update and delete endpoints

import logging

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from services.api_errors import ApiServiceError
from services.error_messages import ERROR_LOGIN_REQUIRED
from services.request_models import (
    MemoCollectionCreateRequest,
    MemoCollectionUpdateRequest,
)
from services.web import (
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


@memo_bp.get("/api/collections", name="memo.api_collections_list")
async def api_list_collections(request: Request):
    """
    所有するコレクションの一覧を取得するエンドポイント
    Endpoint to retrieve list of user's memo collections.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.

    Returns:
        Response: コレクション一覧を含むJSONレスポンス / JSON response listing all collections.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        # DBからコレクション一覧を取得
        # Query collections from the database.
        collections = await _memo_attr("_fetch_collections")(user_id)
        return jsonify({"status": "success", "collections": collections})
    except SQLAlchemyError:
        # コレクション取得失敗時のエラーハンドリング
        # Handle SQL errors during collection retrieval.
        return log_and_internal_server_error(logger, "Failed to load collections.", status="fail")



@memo_bp.post("/api/collections", name="memo.api_collections_create")
async def api_create_collection(request: Request):
    """
    新しいコレクションを作成するエンドポイント
    Endpoint to create a new memo collection.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.

    Returns:
        Response: 作成されたコレクション情報を含むJSONレスポンス / JSON response with created collection info.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # JSON形式の要求を検証
    # Require JSON request dictionary.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # コレクション作成用のパラメータバリデーション
    # Validate payload for collection creation.
    payload, validation_error = validate_payload_model(
        data,
        MemoCollectionCreateRequest,
        error_message="コレクション名を入力してください。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # DBに新しいコレクションを追加
        # Insert a new collection record in the DB.
        collection = await _memo_attr("_insert_collection")(
            user_id, payload.name, payload.color
        )
        return jsonify({"status": "success", "collection": collection})
    except SQLAlchemyError as exc:
        # ユニークキー制約違反（同名コレクション）の場合は409衝突を返す
        # Return 409 Conflict if unique constraint violated (duplicate collection name).
        original = getattr(exc, "orig", None)
        if getattr(original, "sqlstate", None) == "23505" or getattr(
            exc, "sqlstate", None
        ) == "23505":
            return jsonify(
                {"status": "fail", "error": "同名のコレクションが既に存在します。"},
                status_code=409,
            )
        # その他DB書き込みエラー
        # Handle general database insert exception.
        return log_and_internal_server_error(logger, "Failed to create collection.", status="fail")



@memo_bp.patch("/api/collections/{collection_id:int}", name="memo.api_collections_update")
async def api_update_collection(request: Request, collection_id: int):
    """
    コレクション情報を更新するエンドポイント
    Endpoint to update an existing memo collection.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        collection_id (int): 更新対象のコレクションID / Target collection ID to update.

    Returns:
        Response: 更新されたコレクション詳細情報を含むJSONレスポンス / JSON response with updated collection details.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # JSON形式の要求を検証
    # Require JSON request data.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # コレクション更新のパラメータを検証
    # Validate update payload schema.
    payload, validation_error = validate_payload_model(
        data,
        MemoCollectionUpdateRequest,
        error_message="更新データが不正です。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # DBのコレクション情報を更新
        # Update details of the specified collection in DB.
        collection = await _memo_attr("_update_collection")(
            user_id, collection_id, payload.name, payload.color
        )
        return jsonify({"status": "success", "collection": collection})
    except ApiServiceError as exc:
        # コレクションが見つからないなどのサービスエラーを返却
        # Return specific service error if collection is missing or not owned.
        return jsonify_service_error(exc, status="fail")
    except SQLAlchemyError:
        # SQL実行例外などのエラーハンドリング
        # Return 500 status on database update failure.
        return log_and_internal_server_error(logger, "Failed to update collection.", status="fail")



@memo_bp.delete("/api/collections/{collection_id:int}", name="memo.api_collections_delete")
async def api_delete_collection(request: Request, collection_id: int):
    """
    コレクションを削除するエンドポイント
    Endpoint to delete a memo collection.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        collection_id (int): 削除対象のコレクションID / Target collection ID to delete.

    Returns:
        Response: 処理結果を示すJSONレスポンス / Success status JSON.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        # 指定されたコレクションをDBから削除（所属していたメモの関連付けは解除される）
        # Delete the collection from database (memos belonging to it will have association cleared).
        await _memo_attr("_delete_collection")(user_id, collection_id)
        return jsonify({"status": "success"})
    except ApiServiceError as exc:
        # 所有権違反などのサービスエラーを返却
        # Handle authorization or existence service checks.
        return jsonify_service_error(exc, status="fail")
    except SQLAlchemyError:
        # データベース削除処理エラー時のハンドリング
        # Return 500 on database failure.
        return log_and_internal_server_error(logger, "Failed to delete collection.", status="fail")

