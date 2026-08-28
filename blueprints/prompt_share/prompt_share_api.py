"""HTTP endpoints for public prompt sharing.

The blueprint owns request validation and response shaping only.  All database
work is delegated to :class:`SharedContentService`; file processing remains in
the blocking worker because it is filesystem/image work, not database work.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from services.api_errors import ApiServiceError
from services.async_utils import run_blocking
from services.auth_limits import consume_rate_limit, get_request_client_ip
from services.csrf import require_csrf
from services.error_messages import (
    ERROR_GUEST_PROMPT_TEXT_ONLY,
    ERROR_GUEST_PROMPT_URL_FORBIDDEN,
    ERROR_INVALID_PROMPT_FEED_CURSOR,
    ERROR_INVALID_PROMPT_FEED_FILTER,
    ERROR_PROMPT_ATTACHMENT_EMPTY,
    ERROR_PROMPT_ATTACHMENT_NOT_FOUND,
    ERROR_PROMPT_NOT_FOUND,
)
from services.guest_prompt_service import (
    GuestPromptLimitExceeded,
    create_guest_shared_prompt,
    get_or_create_guest_prompt_token,
)
from services.i18n import get_request_locale
from services.prompt_attachment_upload import save_prompt_attachment
from services.prompt_attachment_storage import (
    PROMPT_ATTACHMENT_MAX_BYTES,
    PROMPT_ATTACHMENT_MAX_REQUEST_BYTES,
    delete_prompt_attachment,
    prompt_attachment_content_type,
    resolve_legacy_prompt_attachment_path,
    resolve_prompt_attachment_path,
)
from services.prompt_categories import normalize_category
from services.prompt_types import (
    CONTENT_FORMATS,
    MEDIA_TYPES,
    media_allows_attachment,
    serialize_axes,
)
from services.request_models import (
    PromptCommentCreateRequest,
    PromptCommentReportRequest,
    PromptLikeRequest,
    PromptTaskCreateRequest,
    SharedPromptCreateRequest,
)
from services.shared_content_service import SharedContentService
from services.shared_prompt_service import create_shared_prompt
from services.web import (
    jsonify,
    jsonify_rate_limited,
    jsonify_service_error,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)


prompt_share_api_bp = APIRouter(
    prefix="/prompt_share/api",
    dependencies=[Depends(require_csrf)],
)
logger = logging.getLogger(__name__)

PROMPT_COMMENT_RATE_WINDOW_SECONDS = 300
PROMPT_COMMENT_PER_IP_LIMIT = 20
PROMPT_COMMENT_PER_USER_LIMIT = 12
PROMPT_COMMENT_COOLDOWN_SECONDS = 10
PROMPT_COMMENT_DUPLICATE_WINDOW_SECONDS = 60
PROMPT_COMMENT_LIST_LIMIT = 200
PROMPT_COMMENT_AUTO_HIDE_REPORT_THRESHOLD = 3
PROMPT_COMMENT_MAX_URLS = 3
RECOMMENDED_PROMPT_LIMIT = 3
PROMPT_FEED_DEFAULT_LIMIT = 24
PROMPT_FEED_MAX_LIMIT = 100
PROMPT_CREATE_RATE_WINDOW_SECONDS = 60 * 60
PROMPT_CREATE_PER_IP_LIMIT = 12
PROMPT_CREATE_PER_USER_LIMIT = 8
PROMPT_CREATE_COOLDOWN_SECONDS = 15
GUEST_PROMPT_LINK_PATTERN = re.compile(
    r"(?:\b(?:https?|ftp)://|\bwww\.|\bmailto:)",
    re.IGNORECASE,
)
PROMPT_COMMENT_LINK_PATTERN = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)


def _service() -> SharedContentService:
    return SharedContentService(public_base_url="")


def _parse_prompt_feed_limit(value: str | None) -> int:
    try:
        parsed = int(value) if value is not None else PROMPT_FEED_DEFAULT_LIMIT
    except (TypeError, ValueError):
        return PROMPT_FEED_DEFAULT_LIMIT
    if parsed <= 0:
        return PROMPT_FEED_DEFAULT_LIMIT
    return min(parsed, PROMPT_FEED_MAX_LIMIT)


def _request_body_exceeds_prompt_attachment_limit(request: Request) -> bool:
    raw_length = request.headers.get("content-length")
    if not raw_length:
        return False
    try:
        return int(raw_length) > PROMPT_ATTACHMENT_MAX_REQUEST_BYTES
    except (TypeError, ValueError):
        return True


def _guest_prompt_validation_error(
    payload: SharedPromptCreateRequest,
    raw_data: dict[str, Any],
    has_file_upload: bool,
) -> str | None:
    if payload.content_format != "prompt" or payload.media_type != "text" or has_file_upload:
        return ERROR_GUEST_PROMPT_TEXT_ONLY
    if raw_data.get("attributes") or raw_data.get("resources"):
        return ERROR_GUEST_PROMPT_TEXT_ONLY
    fields = (
        payload.title,
        payload.description,
        payload.content,
        payload.input_examples,
        payload.output_examples,
        payload.ai_model,
    )
    if any(GUEST_PROMPT_LINK_PATTERN.search(value or "") for value in fields):
        return ERROR_GUEST_PROMPT_URL_FORBIDDEN
    return None


def _consume_prompt_create_limits(
    request: Request,
    user_id: int,
) -> tuple[bool, str | None, int | None]:
    client_ip = get_request_client_ip(request)
    checks = (
        ("prompt:create:ip", client_ip, PROMPT_CREATE_PER_IP_LIMIT, PROMPT_CREATE_RATE_WINDOW_SECONDS),
        ("prompt:create:user", str(user_id), PROMPT_CREATE_PER_USER_LIMIT, PROMPT_CREATE_RATE_WINDOW_SECONDS),
        ("prompt:create:cooldown", str(user_id), 1, PROMPT_CREATE_COOLDOWN_SECONDS),
    )
    for key_prefix, identifier, limit, window_seconds in checks:
        allowed, _, retry_after = consume_rate_limit(
            key_prefix,
            identifier,
            limit=limit,
            window_seconds=window_seconds,
        )
        if not allowed:
            return (
                False,
                f"画像付きプロンプトの投稿回数が多すぎます。{retry_after}秒ほど待ってから再試行してください。",
                retry_after,
            )
    return True, None, None


def _decode_prompt_feed_cursor(value: str | None) -> tuple[int, datetime, int] | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        view_count = payload.get("view_count")
        prompt_id = payload.get("id")
        created_at = payload.get("created_at")
        if isinstance(view_count, bool) or isinstance(prompt_id, bool) or not isinstance(created_at, str):
            raise ValueError
        view_count = int(view_count)
        prompt_id = int(prompt_id)
        if view_count < 0 or prompt_id <= 0:
            raise ValueError
        return view_count, datetime.fromisoformat(created_at.replace("Z", "+00:00")), prompt_id
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error) as exc:
        raise ApiServiceError(ERROR_INVALID_PROMPT_FEED_CURSOR, 400) from exc


def _encode_prompt_feed_cursor(prompt: dict[str, Any]) -> str | None:
    created_at = prompt.get("created_at")
    view_count = prompt.get("view_count")
    prompt_id = prompt.get("id")
    if view_count is None or not isinstance(created_at, str) or prompt_id is None:
        return None
    payload = json.dumps(
        {"view_count": int(view_count), "created_at": created_at, "id": int(prompt_id)},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _normalize_prompt_feed_filters(
    category: str | None,
    content_format: str | None,
    media_type: str | None,
) -> tuple[str | None, str | None, str | None]:
    raw_category = str(category or "").strip()
    normalized_category = None
    if raw_category and raw_category.lower() != "all":
        normalized_category = normalize_category(raw_category)
        if normalized_category is None:
            raise ApiServiceError(ERROR_INVALID_PROMPT_FEED_FILTER, 400)
    raw_format = str(content_format or "").strip().lower()
    normalized_format = None if not raw_format or raw_format == "all" else raw_format
    if normalized_format is not None and normalized_format not in CONTENT_FORMATS:
        raise ApiServiceError(ERROR_INVALID_PROMPT_FEED_FILTER, 400)
    raw_media = str(media_type or "").strip().lower()
    normalized_media = None if not raw_media or raw_media == "all" else raw_media
    if normalized_media is not None and normalized_media not in MEDIA_TYPES:
        raise ApiServiceError(ERROR_INVALID_PROMPT_FEED_FILTER, 400)
    return normalized_category, normalized_format, normalized_media


def _serialize_prompt_row(row: dict[str, Any]) -> dict[str, Any]:
    prompt = dict(row)
    created_at = prompt.get("created_at")
    if hasattr(created_at, "isoformat"):
        prompt["created_at"] = created_at.isoformat()
    prompt["description"] = str(prompt.get("description") or "")
    prompt.update(serialize_axes(prompt))
    resources = prompt.get("resources")
    prompt["resources"] = resources if isinstance(resources, list) else []
    if not prompt.get("skill_python_script") and prompt.get("resource_python_script"):
        prompt["skill_python_script"] = str(prompt["resource_python_script"])
    if not prompt.get("skill_python_script"):
        for resource in prompt["resources"]:
            if isinstance(resource, dict) and resource.get("path") == "scripts/main.py":
                if isinstance(resource.get("content"), str):
                    prompt["skill_python_script"] = resource["content"]
                break
    prompt.pop("resource_python_script", None)
    prompt["comment_count"] = int(prompt.get("comment_count") or 0)
    prompt["view_count"] = int(prompt.get("view_count") or 0)
    if "liked" in prompt:
        prompt["liked"] = bool(prompt["liked"])
    if "used_in_chat" in prompt:
        prompt["used_in_chat"] = bool(prompt["used_in_chat"])
    return prompt


def _serialize_prompt_comment_row(row: dict[str, Any], actor_user_id: int | None) -> dict[str, Any]:
    created_at = row.get("created_at")
    user_id = row.get("user_id")
    mine = actor_user_id is not None and user_id == actor_user_id
    can_delete = bool(
        row.get("actor_is_admin")
        or mine
        or (actor_user_id is not None and row.get("prompt_owner_id") == actor_user_id)
    )
    return {
        "id": row.get("id"),
        "prompt_id": row.get("prompt_id"),
        "user_id": user_id,
        "author_name": row.get("author_name") or "ユーザー",
        "content": row.get("content") or "",
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "mine": mine,
        "can_delete": can_delete,
    }


def _contains_too_many_links(content: str) -> bool:
    return len(PROMPT_COMMENT_LINK_PATTERN.findall(content or "")) > PROMPT_COMMENT_MAX_URLS


def _consume_prompt_comment_create_limits(request: Request, user_id: int) -> tuple[bool, str | None, int | None]:
    checks = (
        ("prompt_comment:create:ip", get_request_client_ip(request), PROMPT_COMMENT_PER_IP_LIMIT),
        ("prompt_comment:create:user", str(user_id), PROMPT_COMMENT_PER_USER_LIMIT),
        ("prompt_comment:create:cooldown", str(user_id), 1),
    )
    windows = (
        PROMPT_COMMENT_RATE_WINDOW_SECONDS,
        PROMPT_COMMENT_RATE_WINDOW_SECONDS,
        PROMPT_COMMENT_COOLDOWN_SECONDS,
    )
    for (prefix, identifier, limit), window in zip(checks, windows):
        allowed, _, retry_after = consume_rate_limit(
            prefix,
            identifier,
            limit=limit,
            window_seconds=window,
        )
        if not allowed:
            return False, f"コメント投稿の試行回数が多すぎます。{retry_after}秒ほど待ってから再試行してください。", retry_after
    return True, None, None


def _delete_prompt_attachments(attachments: Any) -> None:
    if isinstance(attachments, list):
        for attachment in attachments:
            delete_prompt_attachment(attachment)


def _save_prompt_attachment(upload_file: Any, user_id: int, media_type: str) -> dict[str, str]:
    filename = getattr(upload_file, "filename", "") or ""
    content_type = getattr(upload_file, "content_type", "") or ""
    file_obj = upload_file.file
    chunks: list[bytes] = []
    total_size = 0
    try:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        while True:
            chunk = file_obj.read(1024 * 1024)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > PROMPT_ATTACHMENT_MAX_BYTES:
                raise ValueError(f"添付ファイルのサイズは{PROMPT_ATTACHMENT_MAX_BYTES // (1024 * 1024)}MB以下にしてください。")
            chunks.append(chunk)
        if total_size == 0:
            raise ValueError(ERROR_PROMPT_ATTACHMENT_EMPTY)
        source = b"".join(chunks)
        return save_prompt_attachment(
            source,
            user_id,
            media_type,
            filename=filename,
            content_type=content_type,
        )
    finally:
        if hasattr(file_obj, "seek"):
            try:
                file_obj.seek(0)
            except Exception:
                pass


async def _get_prompts_with_flags(
    user_id: int | None,
    *,
    limit: int = PROMPT_FEED_DEFAULT_LIMIT,
    cursor: tuple[int, datetime, int] | None = None,
    category: str | None = None,
    content_format: str | None = None,
    media_type: str | None = None,
    author_id: int | None = None,
    locale: str = "ja",
) -> dict[str, Any]:
    rows = await _service().get_public_feed(
        user_id=user_id,
        limit=limit,
        cursor=cursor,
        category=category,
        content_format=content_format,
        media_type=media_type,
        author_id=author_id,
        locale=locale,
    )
    prompts = [_serialize_prompt_row(row) for row in rows]
    has_next = len(prompts) > min(max(int(limit), 1), PROMPT_FEED_MAX_LIMIT)
    page_limit = min(max(int(limit), 1), PROMPT_FEED_MAX_LIMIT)
    prompts = prompts[:page_limit]
    return {
        "prompts": prompts,
        "pagination": {
            "limit": page_limit,
            "has_next": has_next,
            "next_cursor": _encode_prompt_feed_cursor(prompts[-1]) if has_next and prompts else None,
        },
    }


async def _get_recommended_prompts(
    exclude_prompt_id: int | None,
    limit: int = RECOMMENDED_PROMPT_LIMIT,
    locale: str = "ja",
) -> list[dict[str, Any]]:
    rows = await _service().get_recommended_prompts(
        exclude_prompt_id=exclude_prompt_id,
        limit=limit,
        locale=locale,
    )
    return [_serialize_prompt_row(row) for row in rows]


async def _get_public_prompt_by_id(prompt_id: int) -> dict[str, Any] | None:
    row = await _service().get_public_prompt_detail(prompt_id)
    return _serialize_prompt_row(row) if row else None


async def _get_public_author_profile(user_id: int) -> dict[str, Any] | None:
    return await _service().get_public_author_profile(user_id)


@prompt_share_api_bp.get("/media/{filename}", name="prompt_share_api.get_prompt_attachment_media")
async def get_prompt_attachment_media(filename: str):
    try:
        filepath = resolve_prompt_attachment_path(filename)
        media_type = prompt_attachment_content_type(filename)
    except ValueError:
        return jsonify({"error": ERROR_PROMPT_ATTACHMENT_NOT_FOUND}, status_code=404)
    if not os.path.isfile(filepath):
        try:
            filepath = resolve_legacy_prompt_attachment_path(filename)
        except ValueError:
            return jsonify({"error": ERROR_PROMPT_ATTACHMENT_NOT_FOUND}, status_code=404)
        if not os.path.isfile(filepath):
            return jsonify({"error": ERROR_PROMPT_ATTACHMENT_NOT_FOUND}, status_code=404)
    return FileResponse(
        filepath,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"},
    )


@prompt_share_api_bp.get("/prompts", name="prompt_share_api.get_prompts")
async def get_prompts(request: Request, author_id: int | None = None):
    user_id = (getattr(request, "session", {}) or {}).get("user_id")
    try:
        limit = _parse_prompt_feed_limit(request.query_params.get("limit"))
        cursor = _decode_prompt_feed_cursor(request.query_params.get("cursor"))
        category, content_format, media_type = _normalize_prompt_feed_filters(
            request.query_params.get("category"),
            request.query_params.get("content_format"),
            request.query_params.get("media_type"),
        )
        payload = await _get_prompts_with_flags(
            user_id,
            limit=limit,
            cursor=cursor,
            category=category,
            content_format=content_format,
            media_type=media_type,
            author_id=author_id,
            locale=get_request_locale(request),
        )
        return jsonify({"status": "success", **payload})
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to load shared prompts.")


@prompt_share_api_bp.get("/prompts/recommended", name="prompt_share_api.get_recommended_prompts")
async def get_recommended_prompts(request: Request, exclude_id: int | None = None):
    try:
        prompts = await _get_recommended_prompts(
            exclude_id,
            RECOMMENDED_PROMPT_LIMIT,
            get_request_locale(request),
        )
        return jsonify({"status": "success", "prompts": prompts})
    except Exception:
        return log_and_internal_server_error(logger, "Failed to load recommended shared prompts.")


@prompt_share_api_bp.post("/prompts/{prompt_id}/view", name="prompt_share_api.record_prompt_view")
async def record_prompt_view(prompt_id: int):
    try:
        view_count = await _service().record_public_view(prompt_id)
        if view_count is None:
            return jsonify({"error": ERROR_PROMPT_NOT_FOUND}, status_code=404)
        return jsonify({"status": "success", "view_count": int(view_count)})
    except Exception:
        return log_and_internal_server_error(logger, "Failed to record public prompt view.")


@prompt_share_api_bp.get("/prompts/{prompt_id}", name="prompt_share_api.get_prompt_detail")
async def get_prompt_detail(prompt_id: int):
    try:
        prompt = await _get_public_prompt_by_id(prompt_id)
        if not prompt:
            return jsonify({"error": ERROR_PROMPT_NOT_FOUND}, status_code=404)
        return jsonify({"status": "success", "prompt": prompt})
    except Exception:
        return log_and_internal_server_error(logger, "Failed to load public prompt detail.")


@prompt_share_api_bp.get("/users/{user_id}", name="prompt_share_api.get_author_profile")
async def get_author_profile(user_id: int):
    try:
        profile = await _get_public_author_profile(user_id)
        if not profile:
            return jsonify({"error": "ユーザーが見つかりません"}, status_code=404)
        return jsonify({"status": "success", "user": profile})
    except Exception:
        return log_and_internal_server_error(logger, "Failed to load public author profile.")


@prompt_share_api_bp.get("/prompts/{prompt_id}/comments", name="prompt_share_api.get_prompt_comments")
async def get_prompt_comments(prompt_id: int, request: Request):
    session = getattr(request, "session", {}) or {}
    actor_user_id = session.get("user_id")
    actor_is_admin = bool(session.get("is_admin"))
    try:
        comments, comment_count = await _service().list_comments(
            prompt_id=prompt_id,
            limit=PROMPT_COMMENT_LIST_LIMIT,
        )
        if comments is None:
            return jsonify({"error": "対象の公開プロンプトが見つかりませんでした。"}, status_code=404)
        for comment in comments:
            comment["actor_is_admin"] = actor_is_admin
        return jsonify(
            {
                "comments": [_serialize_prompt_comment_row(comment, actor_user_id) for comment in comments],
                "comment_count": comment_count,
            }
        )
    except Exception:
        return log_and_internal_server_error(logger, "Failed to load prompt comments.")


@prompt_share_api_bp.post("/prompts/{prompt_id}/comments", name="prompt_share_api.create_prompt_comment")
async def create_prompt_comment(prompt_id: int, request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = int(request.session["user_id"])
    actor_is_admin = bool(request.session.get("is_admin"))
    allowed, limit_message, retry_after = await run_blocking(
        _consume_prompt_comment_create_limits,
        request,
        user_id,
    )
    if not allowed:
        return jsonify_rate_limited(
            limit_message or "コメント投稿の試行回数が多すぎます。時間をおいて再試行してください。",
            retry_after=retry_after,
        )
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        PromptCommentCreateRequest,
        error_message="コメント内容を入力してください。",
    )
    if validation_error is not None:
        return validation_error
    if _contains_too_many_links(payload.content):
        return jsonify({"error": "URLを含むコメントは3件までにしてください。"}, status_code=400)
    try:
        row, status_code = await _service().add_comment(
            user_id=user_id,
            prompt_id=prompt_id,
            content=payload.content,
            actor_is_admin=actor_is_admin,
            duplicate_window_seconds=PROMPT_COMMENT_DUPLICATE_WINDOW_SECONDS,
        )
        if status_code != 201:
            return jsonify(row, status_code=status_code)
        comment_count = int(row.pop("comment_count", 0))
        row["actor_is_admin"] = actor_is_admin
        return jsonify(
            {
                "message": "コメントを投稿しました。",
                "comment": _serialize_prompt_comment_row(row, user_id),
                "comment_count": comment_count,
            },
            status_code=201,
        )
    except Exception:
        return log_and_internal_server_error(logger, "Failed to create prompt comment.")


@prompt_share_api_bp.delete("/comments/{comment_id}", name="prompt_share_api.delete_prompt_comment")
async def delete_prompt_comment(comment_id: int, request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    try:
        payload, status_code = await _service().delete_comment(
            actor_user_id=int(request.session["user_id"]),
            comment_id=comment_id,
            actor_is_admin=bool(request.session.get("is_admin")),
        )
        if status_code == 200 and "error" not in payload:
            payload = {"message": "コメントを削除しました。", **payload}
        return jsonify(payload, status_code=status_code)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to delete prompt comment.")


@prompt_share_api_bp.post("/comments/{comment_id}/report", name="prompt_share_api.report_prompt_comment")
async def report_prompt_comment(comment_id: int, request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        PromptCommentReportRequest,
        error_message="報告理由を指定してください。",
    )
    if validation_error is not None:
        return validation_error
    try:
        response_payload, status_code = await _service().report_comment(
            reporter_user_id=int(request.session["user_id"]),
            comment_id=comment_id,
            reason=payload.reason,
            details=payload.details,
            auto_hide_threshold=PROMPT_COMMENT_AUTO_HIDE_REPORT_THRESHOLD,
        )
        if "error" not in response_payload:
            if response_payload.get("already_reported"):
                response_payload = {"message": "このコメントはすでに報告済みです。", **response_payload}
            else:
                message = "コメントを報告しました。"
                if response_payload.get("hidden"):
                    message = "コメントを報告しました。一定数の通報により非表示になりました。"
                response_payload = {"message": message, **response_payload}
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to report prompt comment.")


@prompt_share_api_bp.post("/prompts", name="prompt_share_api.create_prompt")
async def create_prompt(request: Request):
    is_guest_post = "user_id" not in request.session
    user_id = request.session.get("user_id")
    if _request_body_exceeds_prompt_attachment_limit(request):
        max_mb = PROMPT_ATTACHMENT_MAX_REQUEST_BYTES // (1024 * 1024)
        return jsonify({"error": f"アップロードリクエストは{max_mb}MB以下にしてください。"}, status_code=413)

    content_type = request.headers.get("content-type", "")
    upload_file = None
    has_file_upload = False
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form(max_files=1, max_fields=32, max_part_size=256 * 1024)
        candidate = form.get("reference_image")
        upload_file = candidate if getattr(candidate, "filename", "") else None
        has_file_upload = any(bool(getattr(value, "filename", "")) for value in form.values())
        try:
            attributes = json.loads(form.get("attributes", "")) if form.get("attributes") else {}
        except (ValueError, TypeError):
            attributes = {}
        try:
            resources = json.loads(form.get("resources", "")) if form.get("resources") else []
        except (ValueError, TypeError):
            resources = []
        data = {
            "title": form.get("title", ""),
            "category": form.get("category", ""),
            "content": form.get("content", ""),
            "description": form.get("description", ""),
            "content_format": form.get("content_format", ""),
            "media_type": form.get("media_type", ""),
            "input_examples": form.get("input_examples", ""),
            "output_examples": form.get("output_examples", ""),
            "ai_model": form.get("ai_model", ""),
            "attributes": attributes if isinstance(attributes, dict) else {},
            "resources": resources if isinstance(resources, list) else [],
        }
    else:
        data, error_response = await require_json_dict(request)
        if error_response is not None:
            return error_response
    payload, validation_error = validate_payload_model(
        data,
        SharedPromptCreateRequest,
        error_message="必要なフィールドが不足しています。",
    )
    if validation_error is not None:
        return validation_error
    if is_guest_post:
        validation_message = _guest_prompt_validation_error(payload, data, has_file_upload)
        if validation_message is not None:
            return jsonify({"error": validation_message}, status_code=400)
        try:
            prompt_id = await create_guest_shared_prompt(
                get_or_create_guest_prompt_token(request.session),
                get_request_client_ip(request),
                payload,
            )
            return jsonify(
                {
                    "message": "ゲストプロンプトが作成されました。登録後に投稿を引き継げます。",
                    "prompt_id": prompt_id,
                    "is_guest": True,
                },
                status_code=201,
            )
        except GuestPromptLimitExceeded as exc:
            return jsonify_rate_limited(str(exc), retry_after=exc.retry_after)
        except Exception:
            return log_and_internal_server_error(logger, "Failed to create guest shared prompt.")

    if upload_file is not None and not media_allows_attachment(payload.media_type):
        return jsonify({"error": "このメディアタイプではファイルを添付できません。"}, status_code=400)
    attachments: list[dict[str, str]] = []
    try:
        if upload_file is not None:
            allowed, limit_message, retry_after = await run_blocking(
                _consume_prompt_create_limits,
                request,
                int(user_id),
            )
            if not allowed:
                return jsonify_rate_limited(limit_message or "画像付き投稿の回数が多すぎます。", retry_after=retry_after)
            attachments = [
                await run_blocking(_save_prompt_attachment, upload_file, int(user_id), payload.media_type)
            ]
        prompt_id = await create_shared_prompt(
            int(user_id),
            payload,
            attachments=attachments,
        )
        return jsonify(
            {"message": "プロンプトが作成されました。", "prompt_id": prompt_id, "is_guest": False},
            status_code=201,
        )
    except ValueError as exc:
        if attachments:
            await run_blocking(_delete_prompt_attachments, attachments)
        return jsonify({"error": str(exc)}, status_code=400)
    except Exception:
        if attachments:
            await run_blocking(_delete_prompt_attachments, attachments)
        return log_and_internal_server_error(logger, "Failed to create shared prompt.")


@prompt_share_api_bp.post("/task", name="prompt_share_api.add_prompt_as_task")
async def add_prompt_as_task(request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        PromptTaskCreateRequest,
        error_message="必要なフィールドが不足しています",
    )
    if validation_error is not None:
        return validation_error
    try:
        response_payload, status_code = await _service().import_prompt_as_task(
            user_id=int(request.session["user_id"]),
            prompt_id=payload.prompt_id,
        )
        if status_code in {200, 201} and "error" not in response_payload:
            response_payload = {
                **response_payload,
                "message": response_payload.get("message") or "チャットで使えるように追加しました。",
                "used_in_chat": True,
            }
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to add prompt as task.")


@prompt_share_api_bp.delete("/task", name="prompt_share_api.remove_prompt_as_task")
async def remove_prompt_as_task(request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        PromptTaskCreateRequest,
        error_message="必要なフィールドが不足しています",
    )
    if validation_error is not None:
        return validation_error
    try:
        response_payload, status_code = await _service().remove_prompt_as_task(
            user_id=int(request.session["user_id"]),
            prompt_id=payload.prompt_id,
        )
        if status_code == 200 and "error" not in response_payload:
            response_payload = {
                **response_payload,
                "message": response_payload.get("message") or "チャットで使う設定を解除しました。",
                "used_in_chat": False,
            }
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to remove prompt as task.")


@prompt_share_api_bp.post("/like", name="prompt_share_api.add_like")
async def add_like(request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        PromptLikeRequest,
        error_message="必要なフィールドが不足しています",
    )
    if validation_error is not None:
        return validation_error
    try:
        response_payload, status_code = await _service().add_like(
            user_id=int(request.session["user_id"]),
            prompt_id=payload.prompt_id,
        )
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        return log_and_internal_server_error(logger, "Failed to add prompt like.")


@prompt_share_api_bp.delete("/like", name="prompt_share_api.remove_like")
async def remove_like(request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        PromptLikeRequest,
        error_message="必要なフィールドが不足しています",
    )
    if validation_error is not None:
        return validation_error
    try:
        await _service().remove_like(
            user_id=int(request.session["user_id"]),
            prompt_id=payload.prompt_id,
        )
        return jsonify({"message": "いいねを解除しました。", "liked": False})
    except Exception:
        return log_and_internal_server_error(logger, "Failed to remove prompt like.")
