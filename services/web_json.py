from __future__ import annotations

import logging
from typing import Any, Dict, TypeVar

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError
from starlette.responses import JSONResponse

from .api_errors import ApiServiceError
from .web_constants import DEFAULT_INTERNAL_ERROR_MESSAGE
from .error_messages import ERROR_INVALID_JSON

ModelT = TypeVar("ModelT", bound=BaseModel)


# 日本語: get json の取得処理を非同期で担当します。
# English: Handle fetching for get json asynchronously.
async def get_json(request: Request) -> Any | None:
    # JSONパース失敗時は例外を外へ出さず None を返す
    # Return None instead of raising when JSON parsing fails.
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        return await request.json()
    except Exception:
        return None


# 日本語: jsonify に関する処理の入口です。
# English: Entry point for logic related to jsonify.
def jsonify(
    payload: Any,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    # FastAPI 互換のJSONエンコードを通してレスポンスを返す
    # Build a JSON response via FastAPI-compatible jsonable encoding.
    response = JSONResponse(content=jsonable_encoder(payload), status_code=status_code)
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for key, value in (headers or {}).items():
        response.headers[str(key)] = str(value)
    return response


# 日本語: jsonify service error に関する処理の入口です。
# English: Entry point for logic related to jsonify service error.
def jsonify_service_error(
    error: ApiServiceError,
    *,
    status: str | None = None,
) -> JSONResponse:
    payload = error.to_payload()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if status is not None:
        payload["status"] = status
    return jsonify(
        payload,
        status_code=error.status_code,
        headers=error.headers,
    )


# 日本語: jsonify rate limited に関する処理の入口です。
# English: Entry point for logic related to jsonify rate limited.
def jsonify_rate_limited(
    message: str,
    *,
    retry_after: int | None,
    status: str | None = None,
    error_key: str = "error",
) -> JSONResponse:
    payload: Dict[str, Any] = {error_key: message}
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if status is not None:
        payload["status"] = status
    headers: dict[str, str] = {}
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if retry_after is not None:
        headers["Retry-After"] = str(max(int(retry_after), 1))
    return jsonify(payload, status_code=429, headers=headers)


# 日本語: log and internal server error に関する処理の入口です。
# English: Entry point for logic related to log and internal server error.
def log_and_internal_server_error(
    logger: logging.Logger,
    context: str,
    *,
    status: str | None = None,
    message: str = DEFAULT_INTERNAL_ERROR_MESSAGE,
    error_key: str = "error",
) -> JSONResponse:
    # ログ出力と500レスポンス生成を共通化する
    # Centralize exception logging and HTTP 500 response creation.
    logger.exception(context)
    payload: Dict[str, Any] = {error_key: message}
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if status is not None:
        payload["status"] = status
    return jsonify(payload, status_code=500)


# 日本語: require json dict に関する処理の入口です。
# English: Entry point for logic related to require json dict.
async def require_json_dict(
    request: Request,
    *,
    error_message: str = ERROR_INVALID_JSON,
    status: str | None = None,
) -> tuple[Dict[str, Any] | None, JSONResponse | None]:
    # リクエストボディがdictであることを保証し、違う場合は400を返す
    # Ensure request body is a dict; otherwise return HTTP 400 response.
    data = await get_json(request)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if isinstance(data, dict):
        return data, None

    payload: Dict[str, Any] = {"error": error_message}
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if status is not None:
        payload["status"] = status
    return None, jsonify(payload, status_code=400)


# 日本語: validate payload model の検証処理を担当します。
# English: Handle validating for validate payload model.
def validate_payload_model(
    data: Dict[str, Any],
    model_class: type[ModelT],
    *,
    error_message: str,
    status: str | None = None,
    error_key: str = "error",
) -> tuple[ModelT | None, JSONResponse | None]:
    # Pydantic v2/v1 両対応でバリデーションし、失敗時は統一エラーを返す
    # Validate payload with Pydantic v2/v1 compatibility and return unified errors.
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        validate = getattr(model_class, "model_validate", None)
        if callable(validate):
            return validate(data), None
        return model_class.parse_obj(data), None  # pragma: no cover - pydantic v1 fallback
    except ValidationError:
        payload: Dict[str, Any] = {error_key: error_message}
        if status is not None:
            payload["status"] = status
        return None, jsonify(payload, status_code=400)
