from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple, TypeVar
from urllib.parse import urlencode

from fastapi import Request
from pydantic import BaseModel, ValidationError
from starlette.responses import JSONResponse, RedirectResponse

from .api_errors import ApiServiceError
from .error_messages import ERROR_INVALID_JSON
from .web_constants import (
    BASE_DIR as _BASE_DIR,
    DEFAULT_INTERNAL_ERROR_MESSAGE,
    FRONTEND_URL,
)
from .web_json import (
    get_json as _get_json,
    jsonify as _jsonify,
    jsonify_rate_limited as _jsonify_rate_limited,
    jsonify_service_error as _jsonify_service_error,
)
from .web_session import (
    flash as _flash,
    get_flashed_messages as _get_flashed_messages,
    set_session_permanent as _set_session_permanent,
)
from .web_urls import (
    build_frontend_url as _build_frontend_url,
    sanitize_next_path as _sanitize_next_path,
    url_for as _url_for,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
BASE_DIR = _BASE_DIR


async def get_json(request: Request) -> Any | None:
    return await _get_json(request)


def jsonify(
    payload: Any,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return _jsonify(payload, status_code=status_code, headers=headers)


def jsonify_service_error(
    error: ApiServiceError,
    *,
    status: str | None = None,
) -> JSONResponse:
    return _jsonify_service_error(error, status=status)


def jsonify_rate_limited(
    message: str,
    *,
    retry_after: int | None,
    status: str | None = None,
    error_key: str = "error",
) -> JSONResponse:
    return _jsonify_rate_limited(
        message,
        retry_after=retry_after,
        status=status,
        error_key=error_key,
    )


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


def set_session_permanent(session: dict, value: bool) -> None:
    return _set_session_permanent(session, value)


def flash(request: Request, message: str, category: str = "message") -> None:
    return _flash(request, message, category=category)


def get_flashed_messages(
    request: Request, *, with_categories: bool = False
) -> List[str] | List[Tuple[str, str]]:
    return _get_flashed_messages(request, with_categories=with_categories)


def url_for(request: Request, endpoint: str, **values: Any) -> str:
    return _url_for(request, endpoint, **values)


def sanitize_next_path(next_path: Any, default: str = "/") -> str:
    return _sanitize_next_path(next_path, default=default)

def frontend_url(path: str = "", *, query: str | None = None) -> str:
    # 既存互換のため、モジュールの FRONTEND_URL を毎回参照してURLを組み立てる
    # Preserve legacy behavior by reading services.web.FRONTEND_URL dynamically.
    return _build_frontend_url(FRONTEND_URL, path, query=query)


def redirect_to_frontend(
    request: Request, path: str | None = None, *, status_code: int = 302
) -> RedirectResponse:
    # 現在パス（または指定パス）をFRONTEND_URLへリダイレクトする
    # Redirect current (or provided) path to FRONTEND_URL.
    target_path = path if path is not None else request.url.path
    query = request.url.query or None
    return RedirectResponse(frontend_url(target_path, query=query), status_code=status_code)


def frontend_login_url(next_path: str | None = None) -> str:
    # ログイン後遷移先を next クエリに埋め込んだログインURLを組み立てる
    # Build login URL with optional post-login `next` query parameter.
    safe_next_path = sanitize_next_path(next_path, default="/") if next_path else None
    query = urlencode({"next": safe_next_path}) if safe_next_path else None
    return frontend_url("/login", query=query)
