from __future__ import annotations

import logging
import os
import sys
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from werkzeug.utils import secure_filename

from services.api_errors import ApiServiceError
from services.async_utils import run_blocking
from services.csrf import require_csrf
from services.db import Error
from services.error_messages import (
    ERROR_LOGIN_REQUIRED,
    ERROR_TOKEN_REQUIRED,
)
from services.request_models import (
    MemoBulkActionRequest,
    MemoCollectionCreateRequest,
    MemoCollectionUpdateRequest,
    MemoCreateRequest,
    MemoReorderRequest,
    MemoShareCreateRequest,
    MemoSuggestRequest,
    MemoToggleRequest,
    MemoUpdateRequest,
    ShareMemoRequest,
)
from services.web import (
    flash,
    get_json,
    jsonify,
    jsonify_service_error,
    log_and_internal_server_error,
    BASE_DIR,
    redirect_to_frontend,
    require_json_dict,
    validate_payload_model,
)

from .constants import DEFAULT_MEMO_LIST_LIMIT, MAX_MEMO_LIST_LIMIT
from .helpers import user_id_from_session

memo_bp = APIRouter(prefix="/memo", dependencies=[Depends(require_csrf)])
logger = logging.getLogger("blueprints.memo")
MEMO_IMAGE_UPLOAD_DIR = os.path.join(BASE_DIR, "frontend", "public", "static", "uploads", "memo")
MEMO_IMAGE_URL_PREFIX = "/static/uploads/memo"
MEMO_IMAGE_MAX_BYTES = 5 * 1024 * 1024
MEMO_IMAGE_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _memo_attr(name: str) -> Any:
    return getattr(sys.modules["blueprints.memo"], name)


def _save_memo_image(upload_file: Any, user_id: int) -> str:
    filename = secure_filename(getattr(upload_file, "filename", "") or "")
    if not filename:
        raise ApiServiceError("画像ファイル名が不正です。", 400, status="fail")

    extension = os.path.splitext(filename)[1].lower()
    if extension not in MEMO_IMAGE_ALLOWED_EXTENSIONS:
        raise ApiServiceError("画像は PNG / JPG / WebP / GIF のいずれかを指定してください。", 400, status="fail")

    content_type = str(getattr(upload_file, "content_type", "") or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise ApiServiceError("画像ファイルのみアップロードできます。", 400, status="fail")

    os.makedirs(MEMO_IMAGE_UPLOAD_DIR, exist_ok=True)
    stored_filename = f"user_{user_id}_{uuid4().hex}{extension}"
    filepath = os.path.join(MEMO_IMAGE_UPLOAD_DIR, stored_filename)
    file_obj = upload_file.file
    total_size = 0

    try:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        with open(filepath, "wb") as out_f:
            while True:
                chunk = file_obj.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MEMO_IMAGE_MAX_BYTES:
                    raise ApiServiceError("画像サイズは5MB以下にしてください。", 400, status="fail")
                out_f.write(chunk)
    except Exception:
        if os.path.exists(filepath):
            os.remove(filepath)
        raise
    finally:
        if hasattr(file_obj, "seek"):
            try:
                file_obj.seek(0)
            except Exception:
                pass

    return f"{MEMO_IMAGE_URL_PREFIX}/{stored_filename}"


@memo_bp.get("/api/recent", name="memo.api_recent")
async def api_recent_memos(
    request: Request,
    limit: int = DEFAULT_MEMO_LIST_LIMIT,
    offset: int = 0,
    q: str = "",
    date_from: str = "",
    date_to: str = "",
    sort: str = "manual",
    include_archived: bool = False,
    only_archived: bool = False,
    pinned_first: bool = True,
    collection_id: int | None = None,
):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    safe_limit = max(1, min(limit, MAX_MEMO_LIST_LIMIT))
    safe_offset = max(0, offset)

    semantic_embedding: list[float] | None = None
    if sort == "semantic" and q.strip() and _memo_attr("embeddings_available")():
        try:
            semantic_embedding = await run_blocking(_memo_attr("generate_embedding"), q.strip())
        except Exception:
            logger.warning("Failed to generate query embedding; falling back to text search.")

    try:
        result = await run_blocking(
            _memo_attr("_fetch_memo_summaries"),
            user_id,
            limit=safe_limit,
            offset=safe_offset,
            query=q,
            date_from=date_from,
            date_to=date_to,
            sort=sort if sort != "semantic" else "recent",
            include_archived=include_archived,
            only_archived=only_archived,
            pinned_first=pinned_first,
            collection_id=collection_id,
            semantic_query_embedding=semantic_embedding,
        )
        return jsonify(result)
    except Error:
        logger.warning("Failed to load memo summaries; returning an empty list.", exc_info=True)
        return jsonify({"memos": [], "total": 0})


@memo_bp.post("/api", name="memo.api_create")
async def api_create_memo(request: Request):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data = await get_json(request)
    if data is None:
        form = await request.form()
        data = {key: value for key, value in form.items()}
    if not isinstance(data, dict):
        data = {}

    payload, validation_error = validate_payload_model(
        data,
        MemoCreateRequest,
        error_message="AIの回答を入力してください。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    resolved_title = _memo_attr("_ensure_title")(payload.ai_response, payload.title)
    try:
        memo_id = await run_blocking(
            _memo_attr("_insert_memo"),
            user_id,
            payload.ai_response,
            resolved_title,
            payload.collection_id,
            payload.background_color,
            payload.image_url,
        )
        flash(request, "メモを保存しました。", "success")
        if memo_id:
            _memo_attr("_schedule_embedding")(memo_id, resolved_title, payload.ai_response)
        return jsonify({"status": "success", "memo_id": memo_id})
    except Error:
        return log_and_internal_server_error(logger, "Failed to create memo entry.", status="fail")


@memo_bp.post("/api/upload-image", name="memo.api_upload_image")
async def api_upload_memo_image(request: Request):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    form = await request.form()
    image_candidate = form.get("image")
    if not getattr(image_candidate, "filename", ""):
        return jsonify({"status": "fail", "error": "画像ファイルを選択してください。"}, status_code=400)

    try:
        image_url = await run_blocking(_save_memo_image, image_candidate, user_id)
        return jsonify({"status": "success", "image_url": image_url})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Exception:
        return log_and_internal_server_error(logger, "Failed to upload memo image.", status="fail")


@memo_bp.post("/api/suggest", name="memo.api_suggest")
async def api_suggest_memo(request: Request):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        MemoSuggestRequest,
        error_message="AIの回答を入力してください。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        result = await run_blocking(
            _memo_attr("suggest_title"),
            payload.ai_response,
        )
        return jsonify({"status": "success", **result})
    except Exception:
        return log_and_internal_server_error(logger, "Memo suggestion failed.", status="fail")


@memo_bp.post("/api/bulk", name="memo.api_bulk")
async def api_bulk_memo(request: Request):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        MemoBulkActionRequest,
        error_message="一括操作のパラメータが不正です。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        result = await run_blocking(
            _memo_attr("_bulk_action"),
            user_id,
            payload.action,
            payload.memo_ids,
            collection_id=payload.collection_id,
        )
        return jsonify({"status": "success", **result})
    except Error:
        return log_and_internal_server_error(logger, "Bulk memo action failed.", status="fail")


@memo_bp.post("/api/reorder", name="memo.api_reorder")
async def api_reorder_memo(request: Request):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        MemoReorderRequest,
        error_message="並べ替えのパラメータが不正です。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        memo = await run_blocking(
            _memo_attr("_reorder_memo"),
            user_id,
            payload.memo_id,
            before_id=payload.before_id,
            after_id=payload.after_id,
        )
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to reorder memo entry.", status="fail")


@memo_bp.get("/api/export", name="memo.api_export")
async def api_export_memos(
    request: Request,
    format: str = "markdown",
    ids: str = "",
):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    memo_ids: list[int] | None = None
    if ids.strip():
        try:
            memo_ids = [int(x.strip()) for x in ids.split(",") if x.strip()]
        except ValueError:
            return jsonify({"status": "fail", "error": "IDの形式が不正です。"}, status_code=400)

    valid_formats = {"markdown", "json", "csv"}
    if format not in valid_formats:
        format = "markdown"

    try:
        memos = await run_blocking(_memo_attr("_fetch_memos_for_export"), user_id, memo_ids)

        if format == "json":
            content = _memo_attr("_build_json_export")(memos)
            media_type = "application/json"
            filename = "memos.json"
        elif format == "csv":
            content = _memo_attr("_build_csv_export")(memos)
            media_type = "text/csv; charset=utf-8"
            filename = "memos.csv"
        else:
            content = _memo_attr("_build_markdown_export")(memos)
            media_type = "text/markdown; charset=utf-8"
            filename = "memos.md"

        return StreamingResponse(
            iter([content.encode("utf-8")]),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
    except Error:
        return log_and_internal_server_error(logger, "Export failed.", status="fail")


@memo_bp.get("/api/collections", name="memo.api_collections_list")
async def api_list_collections(request: Request):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        collections = await run_blocking(_memo_attr("_fetch_collections"), user_id)
        return jsonify({"status": "success", "collections": collections})
    except Error:
        return log_and_internal_server_error(logger, "Failed to load collections.", status="fail")


@memo_bp.post("/api/collections", name="memo.api_collections_create")
async def api_create_collection(request: Request):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        MemoCollectionCreateRequest,
        error_message="コレクション名を入力してください。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        collection = await run_blocking(
            _memo_attr("_insert_collection"), user_id, payload.name, payload.color
        )
        return jsonify({"status": "success", "collection": collection})
    except Error as exc:
        if getattr(exc, "pgcode", None) == "23505":
            return jsonify(
                {"status": "fail", "error": "同名のコレクションが既に存在します。"},
                status_code=409,
            )
        return log_and_internal_server_error(logger, "Failed to create collection.", status="fail")


@memo_bp.patch("/api/collections/{collection_id:int}", name="memo.api_collections_update")
async def api_update_collection(request: Request, collection_id: int):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        MemoCollectionUpdateRequest,
        error_message="更新データが不正です。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        collection = await run_blocking(
            _memo_attr("_update_collection"), user_id, collection_id, payload.name, payload.color
        )
        return jsonify({"status": "success", "collection": collection})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to update collection.", status="fail")


@memo_bp.delete("/api/collections/{collection_id:int}", name="memo.api_collections_delete")
async def api_delete_collection(request: Request, collection_id: int):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        await run_blocking(_memo_attr("_delete_collection"), user_id, collection_id)
        return jsonify({"status": "success"})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to delete collection.", status="fail")


@memo_bp.post("/api/share", name="memo.api_share")
async def api_share_memo(request: Request):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data, ShareMemoRequest, error_message="共有するメモを指定してください。", status="fail",
    )
    if validation_error is not None:
        return validation_error

    share_options, options_error = validate_payload_model(
        data, MemoShareCreateRequest, error_message="共有リンク設定が不正です。", status="fail",
    )
    if options_error is not None:
        return options_error

    try:
        share_state = await run_blocking(
            _memo_attr("create_or_get_shared_memo_token"),
            payload.memo_id,
            user_id,
            force_refresh=share_options.force_refresh,
            expires_in_days=share_options.expires_in_days,
        )
        return jsonify(_memo_attr("_share_payload")(share_state))
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to create share link for memo entry.", status="fail")


@memo_bp.get("/api/shared", name="memo.api_shared")
async def api_shared_memo(request: Request):
    token = request.query_params.get("token", "").strip()
    if not token:
        return jsonify({"error": ERROR_TOKEN_REQUIRED}, status_code=400)

    try:
        payload_result = await run_blocking(_memo_attr("get_shared_memo_payload"), token)
        if isinstance(payload_result, tuple) and len(payload_result) == 2:
            payload, status_code = payload_result
            return jsonify(payload, status_code=status_code)
        return jsonify(payload_result)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Error:
        return log_and_internal_server_error(logger, "Failed to load shared memo payload.")


@memo_bp.get("/api/{memo_id:int}", name="memo.api_detail")
async def api_memo_detail(request: Request, memo_id: int):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        memo = await run_blocking(_memo_attr("_fetch_memo_detail"), user_id, memo_id)
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to load memo detail.", status="fail")


@memo_bp.patch("/api/{memo_id:int}", name="memo.api_update")
async def api_update_memo(request: Request, memo_id: int):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data, MemoUpdateRequest, error_message="更新データが不正です。", status="fail",
    )
    if validation_error is not None:
        return validation_error

    if (
        payload.title is None
        and payload.ai_response is None
        and payload.collection_id is None
        and not payload.clear_collection
        and payload.background_color is None
        and not payload.clear_background_color
        and payload.image_url is None
        and not payload.clear_image
    ):
        return jsonify({"status": "fail", "error": "更新する項目を指定してください。"}, status_code=400)

    try:
        memo = await run_blocking(
            _memo_attr("_update_memo"),
            user_id,
            memo_id,
            title=payload.title,
            ai_response=payload.ai_response,
            collection_id=payload.collection_id,
            clear_collection=payload.clear_collection,
            background_color=payload.background_color,
            clear_background_color=payload.clear_background_color,
            image_url=payload.image_url,
            clear_image=payload.clear_image,
        )
        if payload.ai_response is not None or payload.title is not None:
            _memo_attr("_schedule_embedding")(
                memo_id,
                memo.get("title", ""),
                memo.get("ai_response", ""),
            )
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to update memo entry.", status="fail")


@memo_bp.delete("/api/{memo_id:int}", name="memo.api_delete")
async def api_delete_memo(request: Request, memo_id: int):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        await run_blocking(_memo_attr("_delete_memo"), user_id, memo_id)
        return jsonify({"status": "success"})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to delete memo entry.", status="fail")


@memo_bp.post("/api/{memo_id:int}/archive", name="memo.api_archive")
async def api_archive_memo(request: Request, memo_id: int):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data = await get_json(request)
    if not isinstance(data, dict):
        data = {}

    payload, validation_error = validate_payload_model(
        data, MemoToggleRequest, error_message="アーカイブ設定が不正です。", status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        memo = await run_blocking(_memo_attr("_set_memo_archive_state"), user_id, memo_id, payload.enabled)
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to archive memo entry.", status="fail")


@memo_bp.post("/api/{memo_id:int}/pin", name="memo.api_pin")
async def api_pin_memo(request: Request, memo_id: int):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data = await get_json(request)
    if not isinstance(data, dict):
        data = {}

    payload, validation_error = validate_payload_model(
        data, MemoToggleRequest, error_message="ピン留め設定が不正です。", status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        memo = await run_blocking(_memo_attr("_set_memo_pin_state"), user_id, memo_id, payload.enabled)
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to pin memo entry.", status="fail")


@memo_bp.get("/api/{memo_id:int}/share", name="memo.api_share_detail")
async def api_memo_share_detail(request: Request, memo_id: int):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        share_state = await run_blocking(_memo_attr("get_memo_share_state"), memo_id, user_id)
        return jsonify(_memo_attr("_share_payload")(share_state))
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to load memo share status.", status="fail")


@memo_bp.post("/api/{memo_id:int}/share", name="memo.api_share_refresh")
async def api_memo_share_refresh(request: Request, memo_id: int):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data = await get_json(request)
    if not isinstance(data, dict):
        data = {}

    payload, validation_error = validate_payload_model(
        data, MemoShareCreateRequest, error_message="共有リンク設定が不正です。", status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        share_state = await run_blocking(
            _memo_attr("create_or_get_shared_memo_token"),
            memo_id,
            user_id,
            force_refresh=payload.force_refresh,
            expires_in_days=payload.expires_in_days,
        )
        return jsonify(_memo_attr("_share_payload")(share_state))
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to refresh memo share status.", status="fail")


@memo_bp.post("/api/{memo_id:int}/share/revoke", name="memo.api_share_revoke")
async def api_memo_share_revoke(request: Request, memo_id: int):
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        share_state = await run_blocking(_memo_attr("revoke_shared_memo_token"), memo_id, user_id)
        return jsonify(_memo_attr("_share_payload")(share_state))
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to revoke memo share link.", status="fail")


@memo_bp.api_route("", methods=["GET", "POST"], name="memo.create_memo")
async def create_memo(request: Request):
    status_code = 302 if request.method == "GET" else 303
    return redirect_to_frontend(request, status_code=status_code)
