"""API の JSON 応答を作る共通ヘルパー。

JSON ボディの取得と検証、サービス層のエラーやレート制限・内部エラーの統一形式での応答、
システムメッセージの多言語化を担当する。services/web.py 経由で各ルーターが使う。

Shared helpers that build the API's JSON responses.

Handles reading and validating the JSON body, unified responses for service errors, rate limits and internal errors,
and localization of system messages. Routers use them through services/web.py.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError
from starlette.responses import JSONResponse

from .api_errors import ApiServiceError
from .error_messages import ERROR_INVALID_JSON
from .i18n import translate, translate_text
from .web_constants import DEFAULT_INTERNAL_ERROR_MESSAGE

logger = logging.getLogger(__name__)

# モデルの型変数
# TypeVar for Pydantic models
ModelT = TypeVar("ModelT", bound=BaseModel)


# 日本語: コードを持たない旧来の日本語エラー文から、機械可読なエラーコードへの対応表。未登録の文は "api_error" になる。
# English: Maps legacy Japanese error texts without a code to machine-readable error codes; unlisted texts become "api_error".
_ERROR_CODES_BY_TEXT = {
    "ログインが必要です": "auth.login_required",
    "ログインが必要です。": "auth.login_required",
    "JSON形式が不正です。": "request.invalid_json",
    "該当ルームが見つかりません": "chat.room_not_found",
    "共有リンクが見つかりません": "sharing.link_not_found",
    "共有対象のメモが見つかりません。": "memo.not_found",
}


def _localize_system_payload(payload: Any, status_code: int) -> Any:
    """最上位のシステム用フィールドだけを翻訳し、入れ子になった利用者のコンテンツには触れない。

    Localize only top-level system fields, never nested user content.
    """
    if not isinstance(payload, dict):
        return payload

    localized = dict(payload)
    original_error = localized.get("error")
    for key in ("error", "message", "detail"):
        value = localized.get(key)
        if isinstance(value, str):
            localized[key] = translate_text(value)

    if status_code >= 400 and isinstance(original_error, str):
        localized.setdefault("code", _ERROR_CODES_BY_TEXT.get(original_error, "api_error"))
    return localized


async def get_json(request: Request) -> Any | None:
    # JSONパース失敗時は例外を外へ出さず None を返す
    # Return None instead of raising when JSON parsing fails.
    try:
        return await request.json()
    except Exception:
        # 具体的なパスではなくルートテンプレートを出し、URL 内のトークンをログに残さない
        # Log the route template instead of the concrete path so URL tokens never reach the log
        route = request.scope.get("route")
        logger.debug("Failed to parse the request body as JSON for %s %s.", request.method, getattr(route, "path", "unknown route"))
        return None


def jsonify(
    payload: Any,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    # FastAPI 互換のJSONエンコードを通してレスポンスを返す
    # Build a JSON response via FastAPI-compatible jsonable encoding.
    localized_payload = _localize_system_payload(payload, status_code)
    response = JSONResponse(
        content=jsonable_encoder(localized_payload),
        status_code=status_code,
    )
    for key, value in (headers or {}).items():
        response.headers[str(key)] = str(value)
    return response


def jsonify_service_error(
    error: ApiServiceError,
    *,
    status: str | None = None,
) -> JSONResponse:
    # サービスレイヤーのエラーをJSONレスポンスへシリアライズする
    # Serialize service layer errors into a JSON response.
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
    # レートリミット制限のエラーレスポンスを生成し、Retry-Afterヘッダーを付与する
    # Generate a rate-limit error response and apply the Retry-After header.
    payload: dict[str, Any] = {
        error_key: translate_text(message),
        "code": "rate_limit.exceeded",
    }
    if retry_after is not None:
        payload["params"] = {"retry_after": max(int(retry_after), 1)}
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
    localized_message = (
        translate("common.internal_error")
        if message == DEFAULT_INTERNAL_ERROR_MESSAGE
        else translate_text(message)
    )
    payload: dict[str, Any] = {
        error_key: localized_message,
        "code": "internal_error",
    }
    if status is not None:
        payload["status"] = status
    return jsonify(payload, status_code=500)


async def require_json_dict(
    request: Request,
    *,
    error_message: str = ERROR_INVALID_JSON,
    status: str | None = None,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    # リクエストボディがdictであることを保証し、違う場合は400を返す
    # Ensure request body is a dict; otherwise return HTTP 400 response.
    data = await get_json(request)
    if isinstance(data, dict):
        return data, None

    payload: dict[str, Any] = {
        "error": translate_text(error_message),
        "code": "request.invalid_json",
    }
    if status is not None:
        payload["status"] = status
    return None, jsonify(payload, status_code=400)


def validate_payload_model(
    data: dict[str, Any],
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
        payload: dict[str, Any] = {
            error_key: translate_text(error_message),
            "code": "request.validation_error",
        }
        if status is not None:
            payload["status"] = status
        return None, jsonify(payload, status_code=400)
