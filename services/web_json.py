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


async def get_json(request: Request) -> Any | None:
    # JSONパース失敗時は例外を外へ出さず None を返す
    # Return None instead of raising when JSON parsing fails.
    try:
        return await request.json()
    except Exception:
        return None


def jsonify(
    payload: Any,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    # FastAPI 互換のJSONエンコードを通してレスポンスを返す
    # Build a JSON response via FastAPI-compatible jsonable encoding.
    response = JSONResponse(content=jsonable_encoder(payload), status_code=status_code)
    for key, value in (headers or {}).items():
        response.headers[str(key)] = str(value)
    return response


def jsonify_service_error(
    error: ApiServiceError,
    *,
    status: str | None = None,
) -> JSONResponse:
    payload = error.to_payload()
    if status is not None:
        payload["status"] = status
    return jsonify(
        payload,
        status_code=error.status_code,
        headers=error.headers,
    )


def jsonify_rate_limited(
    message: str,
    *,
    retry_after: int | None,
    status: str | None = None,
    error_key: str = "error",
) -> JSONResponse:
    payload: Dict[str, Any] = {error_key: message}
    if status is not None:
        payload["status"] = status
    headers: dict[str, str] = {}
    if retry_after is not None:
        headers["Retry-After"] = str(max(int(retry_after), 1))
    return jsonify(payload, status_code=429, headers=headers)


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
    if status is not None:
        payload["status"] = status
    return jsonify(payload, status_code=500)


async def require_json_dict(
    request: Request,
    *,
    error_message: str = ERROR_INVALID_JSON,
    status: str | None = None,
) -> tuple[Dict[str, Any] | None, JSONResponse | None]:
    # リクエストボディがdictであることを保証し、違う場合は400を返す
    # Ensure request body is a dict; otherwise return HTTP 400 response.
    data = await get_json(request)
    if isinstance(data, dict):
        return data, None

    payload: Dict[str, Any] = {"error": error_message}
    if status is not None:
        payload["status"] = status
    return None, jsonify(payload, status_code=400)


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
