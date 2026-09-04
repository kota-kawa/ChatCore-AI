from __future__ import annotations

# AI によるメモタイトル提案
# AI title suggestion for a memo body

import logging
import asyncio

from fastapi import Request

from services.error_messages import ERROR_LOGIN_REQUIRED
from services.i18n import get_request_locale
from services.request_models import MemoSuggestRequest
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


@memo_bp.post("/api/suggest", name="memo.api_suggest")
async def api_suggest_memo(request: Request):
    """
    AI回答からおすすめのタイトルを提案するエンドポイント
    Endpoint to suggest an appropriate title from AI response text.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request object.

    Returns:
        Response: 提案されたタイトル候補一覧を含むJSONレスポンス / JSON response containing suggestions.
    """
    # ユーザー認証の確認。未ログインなら401を返却
    # Verify user authentication. Return 401 Unauthorized if not logged in.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    # JSON形式のリクエストデータ取得を強制
    # Require JSON request dictionary.
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    # リクエストボディのフォーマット検証
    # Validate request payload schema.
    payload, validation_error = validate_payload_model(
        data,
        MemoSuggestRequest,
        error_message="AIの回答を入力してください。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        # LLM等を用いて最適なタイトル候補を提案
        # Suggest appropriate title options using the system logic.
        result = await asyncio.to_thread(
            _memo_attr("suggest_title"),
            payload.ai_response,
            locale=get_request_locale(request),
        )
        return jsonify({"status": "success", **result})
    except Exception:
        # 提案処理失敗時のエラーハンドリング
        # Handle exceptions in title suggestion.
        return log_and_internal_server_error(logger, "Memo suggestion failed.", status="fail")

