from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple, TypeVar
from urllib.parse import urlencode

from fastapi import Request
from pydantic import BaseModel
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
    log_and_internal_server_error as _log_and_internal_server_error,
    jsonify_rate_limited as _jsonify_rate_limited,
    jsonify_service_error as _jsonify_service_error,
    require_json_dict as _require_json_dict,
    validate_payload_model as _validate_payload_model,
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

# モデルの型変数とベースディレクトリ
# TypeVar for model validation and base directory definition
ModelT = TypeVar("ModelT", bound=BaseModel)
BASE_DIR = _BASE_DIR


async def get_json(request: Request) -> Any | None:
    # リクエストからJSONデータをパースして取得する
    # Parse and retrieve JSON data from the request
    return await _get_json(request)


def jsonify(
    payload: Any,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    # ペイロードをJSONレスポンスとして返す
    # Return payload as a JSON response
    return _jsonify(payload, status_code=status_code, headers=headers)


def jsonify_service_error(
    error: ApiServiceError,
    *,
    status: str | None = None,
) -> JSONResponse:
    # APIサービスエラーをJSONレスポンスに変換して返す
    # Convert and return an API service error as a JSON response
    return _jsonify_service_error(error, status=status)


def jsonify_rate_limited(
    message: str,
    *,
    retry_after: int | None,
    status: str | None = None,
    error_key: str = "error",
) -> JSONResponse:
    # レートリミットエラーをJSONレスポンスとして返す
    # Return a rate limited error as a JSON response
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
    # 例外をログ出力し、500エラーレスポンスを返す
    # Log exception and return a 500 internal server error response
    return _log_and_internal_server_error(
        logger,
        context,
        status=status,
        message=message,
        error_key=error_key,
    )


async def require_json_dict(
    request: Request,
    *,
    error_message: str = ERROR_INVALID_JSON,
    status: str | None = None,
) -> tuple[Dict[str, Any] | None, JSONResponse | None]:
    # リクエストのペイロードがJSONの辞書であることを保証する
    # Ensure request payload is a JSON dictionary
    return await _require_json_dict(
        request,
        error_message=error_message,
        status=status,
    )


def validate_payload_model(
    data: Dict[str, Any],
    model_class: type[ModelT],
    *,
    error_message: str,
    status: str | None = None,
    error_key: str = "error",
) -> tuple[ModelT | None, JSONResponse | None]:
    # ペイロードデータを指定されたPydanticモデルで検証する
    # Validate payload data against specified Pydantic model
    return _validate_payload_model(
        data,
        model_class,
        error_message=error_message,
        status=status,
        error_key=error_key,
    )


def set_session_permanent(session: dict, value: bool) -> None:
    # セッションの永続化フラグを設定する
    # Set the session permanence flag
    return _set_session_permanent(session, value)


def flash(request: Request, message: str, category: str = "message") -> None:
    # セッションにフラッシュメッセージを追加する
    # Add a flash message to the session
    return _flash(request, message, category=category)


def get_flashed_messages(
    request: Request, *, with_categories: bool = False
) -> List[str] | List[Tuple[str, str]]:
    # セッションからフラッシュメッセージを取得する
    # Retrieve flash messages from the session
    return _get_flashed_messages(request, with_categories=with_categories)


def url_for(request: Request, endpoint: str, **values: Any) -> str:
    # 指定されたエンドポイントのURLを構築する
    # Build a URL for the specified endpoint
    return _url_for(request, endpoint, **values)


def sanitize_next_path(next_path: Any, default: str = "/") -> str:
    # リダイレクト先のパスをサニタイズして安全なパスを返す
    # Sanitize the redirection target path and return a safe path
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
