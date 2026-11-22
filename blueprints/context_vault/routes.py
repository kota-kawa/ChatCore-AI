"""記憶（パーソナル・コンテキスト金庫）の事実・自動抽出の設定・インポート/エクスポートの HTTP API（/api/context-facts）。

HTTP API for memory (the personal context vault): facts, the extraction setting, and import/export (/api/context-facts).
"""
from __future__ import annotations

import json
import logging
import unicodedata

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from services.api_errors import ApiServiceError
from services.context_vault_candidate_service import (
    get_extraction_settings,
    update_extraction_settings,
)
from services.context_vault_portability import (
    build_export,
    confirm_import,
    preview_import,
)
from services.context_vault_service import (
    MAX_CONTEXT_LIST_LIMIT,
    create_fact,
    delete_all_facts,
    delete_fact,
    get_memory_use_settings,
    list_facts,
    revert_replacement,
    update_fact,
    update_memory_use_settings,
)
from services.csrf import require_csrf
from services.error_messages import (
    ERROR_CONTEXT_EXTRACTION_SETTINGS_PAYLOAD_INVALID,
    ERROR_CONTEXT_FACT_DELETE_ALL_CONFIRMATION_REQUIRED,
    ERROR_CONTEXT_FACT_REVISION_REQUIRED,
    ERROR_CONTEXT_FACT_SEARCH_QUERY_INVALID,
    ERROR_CONTEXT_FACT_SEARCH_QUERY_TOO_LONG,
    ERROR_CONTEXT_MEMORY_USE_SETTINGS_PAYLOAD_INVALID,
    ERROR_CONTEXT_VAULT_EXPORT_FORMAT_INVALID,
    ERROR_CONTEXT_VAULT_IMPORT_PAYLOAD_INVALID,
    ERROR_CONTEXT_VAULT_IMPORT_REQUEST_TOO_LARGE,
    ERROR_CONTEXT_VAULT_PORTABILITY_FAILED,
    ERROR_LOGIN_REQUIRED,
)
from services.repositories.memo_helpers import user_id_from_session
from services.request_models import (
    ContextExtractionSettingsUpdateRequest,
    ContextFactCreateRequest,
    ContextFactRevertReplacementRequest,
    ContextFactUpdateRequest,
    ContextMemoryUseSettingsUpdateRequest,
    ContextVaultImportConfirmRequest,
    ContextVaultImportPreviewRequest,
)
from services.response_models import ContextFactDeleteAllResponse
from services.web import (
    jsonify,
    jsonify_service_error,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

from .constants import (
    CONTEXT_FACT_CREATE_ERROR,
    CONTEXT_FACT_DELETE_ERROR,
    CONTEXT_FACT_LIST_ERROR,
    CONTEXT_FACT_UPDATE_ERROR,
    DEFAULT_CONTEXT_LIST_LIMIT,
    DELETE_ALL_CONFIRMATION,
    MAX_CONTEXT_SEARCH_QUERY_LENGTH,
)

# CSRF保護を設定したパーソナル・コンテキスト金庫用APIRouter。
# APIRouter for the personal context vault, with CSRF protection.
context_vault_bp = APIRouter(prefix="/api/context-facts", dependencies=[Depends(require_csrf)])
logger = logging.getLogger("blueprints.context_vault")

# 入力検証に使う許可値と、インポート本文の上限（32MiB）。
# Allowed values for input validation, and the import body size cap (32 MiB).
_VALID_FACT_TYPES = {"preference", "profile", "project", "decision", "reference"}
_VALID_STATUSES = {"active", "deprecated"}
_VALID_PORTABILITY_FORMATS = {"json", "markdown"}
_MAX_CONTEXT_VAULT_IMPORT_REQUEST_BYTES = 32 * 1024 * 1024


# 日本語: 検索語に、空白として語を区切る以外の制御文字(NUL など)が入っているか。PostgreSQL は text に NUL を入れられず、そのまま検索へ
# 渡すと失敗するため、メールアドレスの検証と同じく入力の段階で弾く。
# English: Whether a search query holds a control character other than the whitespace that separates terms (NUL and the like).
# PostgreSQL cannot hold NUL in text, so passing it on would fail the search; it is rejected at input, as email validation does.
def _has_non_whitespace_control_character(value: str) -> bool:
    return any(unicodedata.category(char) == "Cc" and not char.isspace() for char in value)


async def _require_bounded_import_json(request: Request):
    """Content-Length 付きでもチャンク転送でも、上限を超える本文を読み込む前に打ち切ってインポート用 JSON を読む。

    Read an import wrapper with a hard cap for fixed and chunked bodies.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_CONTEXT_VAULT_IMPORT_REQUEST_BYTES:
                return None, jsonify(
                    {
                        "status": "fail",
                        "error": ERROR_CONTEXT_VAULT_IMPORT_REQUEST_TOO_LARGE,
                    },
                    status_code=413,
                )
        except ValueError:
            pass

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_CONTEXT_VAULT_IMPORT_REQUEST_BYTES:
            return None, jsonify(
                {
                    "status": "fail",
                    "error": ERROR_CONTEXT_VAULT_IMPORT_REQUEST_TOO_LARGE,
                },
                status_code=413,
            )
        body.extend(chunk)
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError):
        return None, jsonify(
            {"status": "fail", "error": ERROR_CONTEXT_VAULT_IMPORT_PAYLOAD_INVALID},
            status_code=400,
        )
    if not isinstance(data, dict):
        return None, jsonify(
            {"status": "fail", "error": ERROR_CONTEXT_VAULT_IMPORT_PAYLOAD_INVALID},
            status_code=400,
        )
    return data, None


@context_vault_bp.get("", name="context_vault.api_list")
async def api_list_context_facts(
    request: Request,
    fact_type: str | None = None,
    status: str = "active",
    limit: int = DEFAULT_CONTEXT_LIST_LIMIT,
    cursor: str | None = None,
    q: str | None = None,
):
    # コンテキスト事実の一覧を取得する（種類・状態・検索語でフィルタ、keyset ページング）。
    # List context facts, filtered by type, status and search query, with keyset paging.
    """コンテキスト事実の一覧を取得する（種類・状態・検索語でフィルタ、keyset ページング）。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    if fact_type is not None and fact_type not in _VALID_FACT_TYPES:
        return jsonify({"status": "fail", "error": "種類の指定が不正です。"}, status_code=400)
    if status not in _VALID_STATUSES:
        return jsonify({"status": "fail", "error": "状態の指定が不正です。"}, status_code=400)

    query = q.strip() if q is not None else None
    if query is not None and len(query) > MAX_CONTEXT_SEARCH_QUERY_LENGTH:
        return jsonify({"status": "fail", "error": ERROR_CONTEXT_FACT_SEARCH_QUERY_TOO_LONG}, status_code=400)
    if query is not None and _has_non_whitespace_control_character(query):
        return jsonify({"status": "fail", "error": ERROR_CONTEXT_FACT_SEARCH_QUERY_INVALID}, status_code=400)

    safe_limit = max(1, min(int(limit), MAX_CONTEXT_LIST_LIMIT))
    try:
        result = await list_facts(
            user_id,
            fact_type=fact_type,
            status=status,
            query=query or None,
            limit=safe_limit,
            cursor=cursor,
        )
        return jsonify(result.model_dump())
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(
            logger, "Failed to list memories.", status="fail", message=CONTEXT_FACT_LIST_ERROR, log_exception_text=False
        )


@context_vault_bp.get("/export", name="context_vault.api_export")
async def api_export_context_vault(request: Request, format: str = "json"):
    # 所有者の全事実を、バージョン付きの JSON または Markdown としてダウンロードさせる。
    #
    """Download every owner fact in a safe versioned JSON or Markdown document."""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    if format not in _VALID_PORTABILITY_FORMATS:
        return jsonify(
            {"status": "fail", "error": ERROR_CONTEXT_VAULT_EXPORT_FORMAT_INVALID},
            status_code=400,
        )
    try:
        content, media_type, filename = await build_export(user_id, format)
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(
            logger,
            ERROR_CONTEXT_VAULT_PORTABILITY_FAILED,
            status="fail",
        )


@context_vault_bp.post("/import/preview", name="context_vault.api_import_preview")
async def api_preview_context_vault_import(request: Request):
    # 移行用ドキュメントを検証し、短時間だけ有効な確認トークンを発行する（ドライラン）。
    #
    """Validate a portability document and issue a short-lived confirmation token."""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    data, error_response = await _require_bounded_import_json(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        ContextVaultImportPreviewRequest,
        error_message=ERROR_CONTEXT_VAULT_IMPORT_PAYLOAD_INVALID,
        status="fail",
    )
    if validation_error is not None:
        return validation_error
    try:
        result = await preview_import(user_id, payload.format, payload.content)
        return jsonify(result.model_dump())
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(
            logger,
            ERROR_CONTEXT_VAULT_PORTABILITY_FAILED,
            status="fail",
        )


@context_vault_bp.post("/import", name="context_vault.api_import")
async def api_import_context_vault(request: Request):
    # 直前のドライランで受理された内容と同一のドキュメントだけを、既存の事実へ追記する。
    #
    """Append only the exact document accepted by a preceding dry-run."""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    data, error_response = await _require_bounded_import_json(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        ContextVaultImportConfirmRequest,
        error_message=ERROR_CONTEXT_VAULT_IMPORT_PAYLOAD_INVALID,
        status="fail",
    )
    if validation_error is not None:
        return validation_error
    try:
        result = await confirm_import(
            user_id,
            payload.format,
            payload.content,
            payload.preview_token,
        )
        return jsonify(result.model_dump())
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(
            logger,
            ERROR_CONTEXT_VAULT_PORTABILITY_FAILED,
            status="fail",
        )


@context_vault_bp.get(
    "/extraction-settings",
    name="context_vault.api_get_extraction_settings",
)
async def api_get_context_extraction_settings(request: Request):
    # 現在の会話からの記憶の自動抽出の設定（初期値は有効）を取得する。
    # Get the current setting for automatic memory extraction from conversations (on by default).
    """現在の会話からの記憶の自動抽出の設定（初期値は有効）を取得する。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    try:
        result = await get_extraction_settings(user_id)
        return jsonify(result.model_dump())
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(logger, CONTEXT_FACT_UPDATE_ERROR, status="fail")


@context_vault_bp.put(
    "/extraction-settings",
    name="context_vault.api_update_extraction_settings",
)
async def api_update_context_extraction_settings(request: Request):
    # 会話からの記憶の自動抽出をユーザーの明示操作で有効・無効化する。
    # Enable or disable automatic memory extraction through an explicit user action.
    """会話からの記憶の自動抽出をユーザーの明示操作で有効・無効化する。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        ContextExtractionSettingsUpdateRequest,
        error_message=ERROR_CONTEXT_EXTRACTION_SETTINGS_PAYLOAD_INVALID,
        status="fail",
    )
    if validation_error is not None:
        return validation_error
    try:
        result = await update_extraction_settings(user_id, payload.enabled)
        return jsonify({"status": "success", **result.model_dump()})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")


@context_vault_bp.get(
    "/memory-use-settings",
    name="context_vault.api_get_memory_use_settings",
)
async def api_get_context_memory_use_settings(request: Request):
    # 保存した記憶をチャットの回答に使う設定（初期値は有効）を取得する。
    # Get the setting for using saved memory in chat answers (on by default).
    """保存した記憶をチャットの回答に使う設定（初期値は有効）を取得する。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    try:
        result = await get_memory_use_settings(user_id)
        return jsonify(result.model_dump())
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(logger, CONTEXT_FACT_UPDATE_ERROR, status="fail")


@context_vault_bp.put(
    "/memory-use-settings",
    name="context_vault.api_update_memory_use_settings",
)
async def api_update_context_memory_use_settings(request: Request):
    # 保存した記憶をチャットの回答に使うかを、ユーザーの明示操作で切り替える。
    # Switch whether saved memory is used in chat answers through an explicit user action.
    """保存した記憶をチャットの回答に使うかを、ユーザーの明示操作で切り替える。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        ContextMemoryUseSettingsUpdateRequest,
        error_message=ERROR_CONTEXT_MEMORY_USE_SETTINGS_PAYLOAD_INVALID,
        status="fail",
    )
    if validation_error is not None:
        return validation_error
    try:
        result = await update_memory_use_settings(user_id, payload.enabled)
        return jsonify({"status": "success", **result.model_dump()})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")


@context_vault_bp.post("", name="context_vault.api_create")
async def api_create_context_fact(request: Request):
    # コンテキスト事実を新規作成する。
    # Create a new context fact.
    """コンテキスト事実を新規作成する。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        ContextFactCreateRequest,
        error_message="種類・タイトル・内容を入力してください。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        fact = await create_fact(
            user_id,
            fact_type=payload.fact_type,
            title=payload.title,
            content=payload.content,
            importance=payload.importance,
        )
        return jsonify({"status": "success", "fact": fact.model_dump()})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(logger, CONTEXT_FACT_CREATE_ERROR, status="fail")


@context_vault_bp.put("/{fact_id:int}", name="context_vault.api_update")
async def api_update_context_fact(request: Request, fact_id: int):
    # コンテキスト事実を更新する（無効化・復元も status で行う、revision で競合検出）。
    # Update a context fact; deprecating or restoring is done via status, and revision detects conflicts.
    """コンテキスト事実を更新する（無効化・復元も status で行う、revision で競合検出）。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        ContextFactUpdateRequest,
        error_message="更新内容とrevisionを指定してください。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        fact = await update_fact(
            user_id,
            fact_id,
            expected_revision=payload.revision,
            title=payload.title,
            content=payload.content,
            fact_type=payload.fact_type,
            status=payload.status,
            importance=payload.importance,
            confirmed_by_owner=True,
        )
        return jsonify({"status": "success", "fact": fact.model_dump()})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(logger, CONTEXT_FACT_UPDATE_ERROR, status="fail")


@context_vault_bp.post("/{fact_id:int}/revert-replacement", name="context_vault.api_revert_replacement")
async def api_revert_context_fact_replacement(request: Request, fact_id: int):
    # 置き換えで入った新しい記憶を無効化し、置き換えられた古い記憶を有効へ戻す（revision は新しい記憶のもの）。
    # Deprecate the memory that came in by replacement and restore the older one it replaced; revision is the new memory's.
    """置き換えで入った新しい記憶を無効化し、置き換えられた古い記憶を有効へ戻す。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        ContextFactRevertReplacementRequest,
        error_message=ERROR_CONTEXT_FACT_REVISION_REQUIRED,
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        result = await revert_replacement(user_id, fact_id, expected_revision=payload.revision)
        return jsonify({"status": "success", **result.model_dump()})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(
            logger, "Failed to revert a memory replacement.", status="fail", message=CONTEXT_FACT_UPDATE_ERROR, log_exception_text=False
        )


@context_vault_bp.delete("/{fact_id:int}", name="context_vault.api_delete")
async def api_delete_context_fact(request: Request, fact_id: int, revision: int | None = None):
    # 記憶 1 件を、有効・無効化済みのどちらでも完全に削除する（無効化とは違い、文面ごと消える）。revision で競合検出する。
    # Delete one memory for good, active or deprecated (unlike deprecating, the wording is erased); revision detects conflicts.
    """記憶 1 件を完全に削除する。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    if revision is None or revision < 1:
        return jsonify({"status": "fail", "error": ERROR_CONTEXT_FACT_REVISION_REQUIRED}, status_code=400)

    try:
        await delete_fact(user_id, fact_id, expected_revision=revision)
        return jsonify({"status": "success"})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(
            logger, "Failed to delete a memory.", status="fail", message=CONTEXT_FACT_DELETE_ERROR, log_exception_text=False
        )


@context_vault_bp.delete("", name="context_vault.api_delete_all")
async def api_delete_all_context_facts(request: Request, confirm: str | None = None):
    # 自分の記憶・出典・候補をすべて削除する。誤操作を防ぐため confirm に確認の値を要求する。自動で記憶する設定と回答に使う設定は変えない。
    # Delete all of the owner's memories, sources and candidates; confirm must carry the confirmation value to prevent accidents.
    # The saving and use-in-answers settings are left as they are.
    """自分の記憶をすべて削除する。"""
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)
    if confirm != DELETE_ALL_CONFIRMATION:
        return jsonify(
            {"status": "fail", "error": ERROR_CONTEXT_FACT_DELETE_ALL_CONFIRMATION_REQUIRED},
            status_code=400,
        )

    try:
        deleted_count = await delete_all_facts(user_id)
        return jsonify({"status": "success", **ContextFactDeleteAllResponse(deleted_count=deleted_count).model_dump()})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(
            logger, "Failed to delete all memories.", status="fail", message=CONTEXT_FACT_DELETE_ERROR, log_exception_text=False
        )
