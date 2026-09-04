from __future__ import annotations

# 手動並び順（ドラッグ＆ドロップ）の保存
# Manual (drag-and-drop) ordering

import logging

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from services.api_errors import ApiServiceError
from services.error_messages import ERROR_LOGIN_REQUIRED
from services.request_models import MemoReorderRequest
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


@memo_bp.post("/api/reorder", name="memo.api_reorder")
async def api_reorder_memo(request: Request):
    """
    メモの並び順（ドラッグ＆ドロップ順）を更新するエンドポイント
    Endpoint to update manual sort sequence of a memo (drag and drop).

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.

    Returns:
        Response: 更新されたメモ情報を含むJSONレスポンス / JSON response containing updated memo details.
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

    # 並び替えパラメータの検証
    # Validate payload parameters.
    payload, validation_error = validate_payload_model(
        data,
        MemoReorderRequest,
        error_message="並べ替えのパラメータが不正です。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # メモのソート順序位置を更新
        # Update the position of the target memo relative to target neighbors.
        memo = await _memo_attr("_reorder_memo")(
            user_id,
            payload.memo_id,
            before_id=payload.before_id,
            after_id=payload.after_id,
        )
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        # メモが見つからないなど、バリデーションエラーの場合は例外ハンドラに応じたレスポンスを返す
        # Handle business logic exceptions and return appropriate error payload.
        return jsonify_service_error(exc, status="fail")
    except SQLAlchemyError:
        # DB書き込み失敗時のエラーハンドリング
        # Handle database connection or SQL exception.
        return log_and_internal_server_error(logger, "Failed to reorder memo entry.", status="fail")

