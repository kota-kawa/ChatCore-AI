from __future__ import annotations

# ゴミ箱のメモの復元・完全削除・ゴミ箱を空にする操作
# Restore, permanent delete and empty-trash endpoints for trashed memos
import logging

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from services.api_errors import ApiServiceError
from services.error_messages import ERROR_LOGIN_REQUIRED
from services.repositories.memo_helpers import user_id_from_session
from services.web import (
    jsonify,
    jsonify_service_error,
    log_and_internal_server_error,
)

from . import memo_bp
from ._common import _memo_attr

logger = logging.getLogger(__name__)


@memo_bp.post("/api/{memo_id:int}/restore", name="memo.api_restore")
async def api_restore_memo(request: Request, memo_id: int):
    """
    ゴミ箱のメモを元に戻すエンドポイント（アーカイブ・ピン留めなどは削除前のまま）
    Endpoint to restore a trashed memo; its archive and pin state stay as they were before deletion.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        memo_id (int): 復元するメモID / The memo ID to restore.

    Returns:
        Response: 復元されたメモ情報を含むJSONレスポンス / JSON response with the restored memo.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        memo = await _memo_attr("_restore_memo")(user_id, memo_id)
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        # ゴミ箱にない・他人のメモは「見つからない」として返す
        # A memo outside the trash, or someone else's, is reported as not found.
        return jsonify_service_error(exc, status="fail")
    except SQLAlchemyError:
        return log_and_internal_server_error(logger, "Failed to restore memo entry.", status="fail")


@memo_bp.delete("/api/trash/{memo_id:int}", name="memo.api_purge")
async def api_purge_memo(request: Request, memo_id: int):
    """
    ゴミ箱内のメモ1件を完全に削除するエンドポイント
    Endpoint to permanently delete one memo that is in the trash.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        memo_id (int): 完全に削除するメモID / The memo ID to delete permanently.

    Returns:
        Response: 処理結果を示すJSONレスポンス / Success status JSON.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        await _memo_attr("_purge_memo")(user_id, memo_id)
        return jsonify({"status": "success"})
    except ApiServiceError as exc:
        # ゴミ箱にないメモは完全削除できない（見つからない扱い）
        # A memo outside the trash cannot be purged and is reported as not found.
        return jsonify_service_error(exc, status="fail")
    except SQLAlchemyError:
        return log_and_internal_server_error(logger, "Failed to purge memo entry.", status="fail")


@memo_bp.delete("/api/trash", name="memo.api_empty_trash")
async def api_empty_memo_trash(request: Request):
    """
    ログインユーザーのゴミ箱をすべて完全に削除するエンドポイント
    Endpoint to permanently delete every trashed memo of the signed-in user.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.

    Returns:
        Response: 削除件数を含むJSONレスポンス / JSON response with the number of deleted memos.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        deleted = await _memo_attr("_empty_memo_trash")(user_id)
        return jsonify({"status": "success", "deleted": deleted})
    except SQLAlchemyError:
        return log_and_internal_server_error(logger, "Failed to empty the memo trash.", status="fail")
