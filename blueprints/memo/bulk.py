from __future__ import annotations

# 複数メモへの一括操作
# Bulk actions over several memos

import logging

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from services.error_messages import ERROR_LOGIN_REQUIRED
from services.request_models import MemoBulkActionRequest
from services.web import (
    jsonify,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

from services.repositories.memo_helpers import user_id_from_session

from . import memo_bp
from ._common import _memo_attr

logger = logging.getLogger(__name__)


@memo_bp.post("/api/bulk", name="memo.api_bulk")
async def api_bulk_memo(request: Request):
    """
    複数メモに対して一括操作を行うエンドポイント
    Endpoint to perform bulk operations on multiple memos.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.

    Returns:
        Response: 一括操作の実行結果を含むJSONレスポンス / JSON response of execution results.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # JSON形式のリクエストデータ取得を強制
    # Require JSON format payload.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # バリデーション実行
    # Validate bulk parameters.
    payload, validation_error = validate_payload_model(
        data,
        MemoBulkActionRequest,
        error_message="一括操作のパラメータが不正です。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # 指定された一括アクション（削除、ピン留め、アーカイブ、コレクション設定など）を実行
        # Execute the bulk action (delete, pin, archive, set collection) on given memo IDs.
        result = await _memo_attr("_bulk_action")(
            user_id,
            payload.action,
            payload.memo_ids,
            collection_id=payload.collection_id,
        )
        return jsonify({"status": "success", **result})
    except SQLAlchemyError:
        # 一括処理DBエラー時のハンドリング
        # Return internal server error if bulk DB query fails.
        return log_and_internal_server_error(logger, "Bulk memo action failed.", status="fail")

