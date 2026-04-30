from __future__ import annotations

import json
import logging
from datetime import date, datetime, time
from typing import Any

from fastapi import APIRouter, Depends, Request

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.async_utils import run_blocking
from services.csrf import require_csrf
from services.datetime_serialization import serialize_datetime_iso
from services.db import Error, get_db_connection
from services.error_messages import (
    ERROR_LOGIN_REQUIRED,
    ERROR_MEMO_NOT_FOUND_FOR_SHARE,
    ERROR_TOKEN_REQUIRED,
)
from services.memo_share import (
    create_or_get_shared_memo_token,
    get_memo_share_state,
    get_shared_memo_payload,
    revoke_shared_memo_token,
)
from services.request_models import (
    MemoCreateRequest,
    MemoShareCreateRequest,
    MemoToggleRequest,
    MemoUpdateRequest,
    ShareMemoRequest,
)
from services.web import (
    flash,
    frontend_url,
    get_json,
    jsonify,
    jsonify_service_error,
    log_and_internal_server_error,
    redirect_to_frontend,
    require_json_dict,
    validate_payload_model,
)

MEMO_NOT_FOUND_ERROR = "メモが見つかりません。"
DEFAULT_MEMO_LIST_LIMIT = 20
MAX_MEMO_LIST_LIMIT = 100
DEFAULT_EXCERPT_LENGTH = 180

memo_bp = APIRouter(prefix="/memo", dependencies=[Depends(require_csrf)])
logger = logging.getLogger(__name__)


def _ensure_title(ai_response: str, provided_title: str) -> str:
    """Generate a fallback title from the AI response when none is supplied."""
    title = provided_title.strip()
    if title:
        return title[:255]

    for line in ai_response.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:255]

    return "新しいメモ"


def _user_id_from_session(session: dict[str, Any]) -> int | None:
    user_id = session.get("user_id")
    if isinstance(user_id, int):
        return user_id
    return None


def _parse_memo_text(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, str):
            return parsed
    except (TypeError, ValueError):
        pass
    return raw


def _is_expired(expires_at: Any) -> bool:
    if not isinstance(expires_at, datetime):
        return False
    return expires_at <= datetime.utcnow()


def _parse_date_filter(raw: str) -> date | None:
    normalized = raw.strip()
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _serialize_share_meta(memo: dict[str, Any]) -> dict[str, Any]:
    share_token = memo.get("share_token") or ""
    expires_at = memo.get("expires_at")
    revoked_at = memo.get("revoked_at")
    is_active = bool(share_token) and revoked_at is None and not _is_expired(expires_at)
    return {
        "share_token": share_token,
        "expires_at": serialize_datetime_iso(expires_at),
        "revoked_at": serialize_datetime_iso(revoked_at),
        "is_expired": _is_expired(expires_at),
        "is_revoked": revoked_at is not None,
        "is_active": is_active,
        "share_url": frontend_url(f"/shared/memo/{share_token}") if is_active else "",
    }


def _serialize_memo_summary(memo: dict[str, Any]) -> dict[str, Any]:
    preview_source = _parse_memo_text(memo.get("preview_response") or "")
    share_meta = _serialize_share_meta(memo)
    return {
        "id": memo.get("id"),
        "title": memo.get("title") or "保存したメモ",
        "tags": memo.get("tags") or "",
        "created_at": serialize_datetime_iso(memo.get("created_at")),
        "updated_at": serialize_datetime_iso(memo.get("updated_at")),
        "archived_at": serialize_datetime_iso(memo.get("archived_at")),
        "pinned_at": serialize_datetime_iso(memo.get("pinned_at")),
        "is_archived": memo.get("archived_at") is not None,
        "is_pinned": memo.get("pinned_at") is not None,
        "excerpt": preview_source[:DEFAULT_EXCERPT_LENGTH],
        **share_meta,
    }


def _serialize_memo_detail(memo: dict[str, Any]) -> dict[str, Any]:
    share_meta = _serialize_share_meta(memo)
    return {
        "id": memo.get("id"),
        "title": memo.get("title") or "保存したメモ",
        "tags": memo.get("tags") or "",
        "created_at": serialize_datetime_iso(memo.get("created_at")),
        "updated_at": serialize_datetime_iso(memo.get("updated_at")),
        "archived_at": serialize_datetime_iso(memo.get("archived_at")),
        "pinned_at": serialize_datetime_iso(memo.get("pinned_at")),
        "is_archived": memo.get("archived_at") is not None,
        "is_pinned": memo.get("pinned_at") is not None,
        "input_content": memo.get("input_content") or "",
        "ai_response": memo.get("ai_response") or "",
        **share_meta,
    }


def _resolve_sort_order(sort: str) -> str:
    if sort == "oldest":
        return "me.created_at ASC"
    if sort == "updated":
        return "me.updated_at DESC"
    if sort == "title":
        return "LOWER(me.title) ASC, me.created_at DESC"
    return "me.created_at DESC"


def _fetch_memo_summaries(
    user_id: int,
    *,
    limit: int,
    offset: int,
    query: str,
    tag: str,
    date_from: str,
    date_to: str,
    sort: str,
    include_archived: bool,
    only_archived: bool,
    pinned_first: bool,
) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        where_clauses = ["me.user_id = %s"]
        filter_params: list[Any] = [user_id]

        if only_archived:
            where_clauses.append("me.archived_at IS NOT NULL")
        elif not include_archived:
            where_clauses.append("me.archived_at IS NULL")

        normalized_query = query.strip()
        if normalized_query:
            query_like = f"%{normalized_query}%"
            where_clauses.append(
                """
                (
                    me.title ILIKE %s
                    OR me.tags ILIKE %s
                    OR me.input_content ILIKE %s
                    OR me.ai_response ILIKE %s
                )
                """
            )
            filter_params.extend([query_like, query_like, query_like, query_like])

        normalized_tag = tag.strip()
        if normalized_tag:
            filter_params.append(f"%{normalized_tag}%")
            where_clauses.append("me.tags ILIKE %s")

        parsed_date_from = _parse_date_filter(date_from)
        if parsed_date_from is not None:
            filter_params.append(datetime.combine(parsed_date_from, time.min))
            where_clauses.append("me.created_at >= %s")

        parsed_date_to = _parse_date_filter(date_to)
        if parsed_date_to is not None:
            filter_params.append(datetime.combine(parsed_date_to, time.max))
            where_clauses.append("me.created_at <= %s")

        where_sql = " AND ".join(where_clauses)

        order_by_parts: list[str] = []
        if pinned_first:
            order_by_parts.append("CASE WHEN me.pinned_at IS NULL THEN 1 ELSE 0 END ASC")
            order_by_parts.append("me.pinned_at DESC")
        order_by_parts.append(_resolve_sort_order(sort))
        order_sql = ", ".join(order_by_parts)

        count_sql = f"""
            SELECT COUNT(*) AS total_count
            FROM memo_entries me
            WHERE {where_sql}
        """
        cursor.execute(count_sql, tuple(filter_params))
        count_row = cursor.fetchone() or {}
        total_count = int(count_row.get("total_count") or 0)

        list_sql = f"""
            SELECT
                me.id,
                me.title,
                me.tags,
                me.created_at,
                me.updated_at,
                me.archived_at,
                me.pinned_at,
                LEFT(COALESCE(me.ai_response, ''), 400) AS preview_response,
                sme.share_token,
                sme.expires_at,
                sme.revoked_at
            FROM memo_entries me
            LEFT JOIN shared_memo_entries sme ON sme.memo_entry_id = me.id
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT %s OFFSET %s
        """
        list_params = [*filter_params, limit, offset]
        cursor.execute(list_sql, tuple(list_params))
        rows = list(cursor.fetchall())
        return {
            "total": total_count,
            "memos": [_serialize_memo_summary(row) for row in rows],
        }
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def _fetch_memo_detail(user_id: int, memo_id: int) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                me.id,
                me.title,
                me.tags,
                me.input_content,
                me.ai_response,
                me.created_at,
                me.updated_at,
                me.archived_at,
                me.pinned_at,
                sme.share_token,
                sme.expires_at,
                sme.revoked_at
            FROM memo_entries me
            LEFT JOIN shared_memo_entries sme ON sme.memo_entry_id = me.id
            WHERE me.id = %s AND me.user_id = %s
            LIMIT 1
            """,
            (memo_id, user_id),
        )
        row = cursor.fetchone()
        if not row:
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
        return _serialize_memo_detail(row)
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def _insert_memo(
    user_id: int,
    input_content: str,
    ai_response: str,
    resolved_title: str,
    tags: str,
) -> int | None:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO memo_entries (user_id, input_content, ai_response, title, tags)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (user_id, input_content, ai_response, resolved_title, tags or None),
        )
        connection.commit()
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def _update_memo(
    user_id: int,
    memo_id: int,
    *,
    title: str | None,
    tags: str | None,
    input_content: str | None,
    ai_response: str | None,
) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT title, tags, input_content, ai_response
            FROM memo_entries
            WHERE id = %s AND user_id = %s
            LIMIT 1
            """,
            (memo_id, user_id),
        )
        existing = cursor.fetchone()
        if not existing:
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)

        resolved_ai_response = existing.get("ai_response") or ""
        if ai_response is not None:
            resolved_ai_response = ai_response
        if not str(resolved_ai_response).strip():
            raise ApiServiceError("AIの回答を入力してください。", 400, status="fail")

        resolved_title = existing.get("title") or ""
        if title is not None:
            resolved_title = _ensure_title(str(resolved_ai_response), title)

        resolved_tags = existing.get("tags")
        if tags is not None:
            normalized_tags = tags.strip()
            resolved_tags = normalized_tags or None

        resolved_input = existing.get("input_content") or ""
        if input_content is not None:
            resolved_input = input_content

        cursor.execute(
            """
            UPDATE memo_entries
            SET title = %s, tags = %s, input_content = %s, ai_response = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s
            """,
            (
                resolved_title,
                resolved_tags,
                resolved_input,
                resolved_ai_response,
                memo_id,
                user_id,
            ),
        )
        connection.commit()
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return _fetch_memo_detail(user_id, memo_id)


def _set_memo_archive_state(user_id: int, memo_id: int, enabled: bool) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE memo_entries
            SET archived_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s
            RETURNING id
            """,
            (enabled, memo_id, user_id),
        )
        if not cursor.fetchone():
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
        connection.commit()
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return _fetch_memo_detail(user_id, memo_id)


def _set_memo_pin_state(user_id: int, memo_id: int, enabled: bool) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE memo_entries
            SET pinned_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s
            RETURNING id
            """,
            (enabled, memo_id, user_id),
        )
        if not cursor.fetchone():
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
        connection.commit()
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return _fetch_memo_detail(user_id, memo_id)


def _delete_memo(user_id: int, memo_id: int) -> None:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            DELETE FROM memo_entries
            WHERE id = %s AND user_id = %s
            RETURNING id
            """,
            (memo_id, user_id),
        )
        if not cursor.fetchone():
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
        connection.commit()
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def _share_payload(share_state: dict[str, Any]) -> dict[str, Any]:
    share_token = str(share_state.get("share_token") or "")
    share_url = ""
    if share_token and bool(share_state.get("is_active")):
        share_url = frontend_url(f"/shared/memo/{share_token}")
    return {
        "status": "success",
        **share_state,
        "share_url": share_url,
    }


@memo_bp.get("/api/recent", name="memo.api_recent")
async def api_recent_memos(
    request: Request,
    limit: int = DEFAULT_MEMO_LIST_LIMIT,
    offset: int = 0,
    q: str = "",
    tag: str = "",
    date_from: str = "",
    date_to: str = "",
    sort: str = "recent",
    include_archived: bool = False,
    only_archived: bool = False,
    pinned_first: bool = True,
):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    safe_limit = max(1, min(limit, MAX_MEMO_LIST_LIMIT))
    safe_offset = max(0, offset)
    try:
        result = await run_blocking(
            _fetch_memo_summaries,
            user_id,
            limit=safe_limit,
            offset=safe_offset,
            query=q,
            tag=tag,
            date_from=date_from,
            date_to=date_to,
            sort=sort,
            include_archived=include_archived,
            only_archived=only_archived,
            pinned_first=pinned_first,
        )
        return jsonify(result)
    except Error:
        logger.warning("Failed to load memo summaries; returning an empty list.", exc_info=True)
        return jsonify({"memos": [], "total": 0})


@memo_bp.post("/api", name="memo.api_create")
async def api_create_memo(request: Request):
    user_id = _user_id_from_session(request.session)
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

    resolved_title = _ensure_title(payload.ai_response, payload.title)
    try:
        memo_id = await run_blocking(
            _insert_memo,
            user_id,
            payload.input_content,
            payload.ai_response,
            resolved_title,
            payload.tags,
        )
        flash(request, "メモを保存しました。", "success")
        return jsonify({"status": "success", "memo_id": memo_id})
    except Error:
        return log_and_internal_server_error(
            logger,
            "Failed to create memo entry.",
            status="fail",
        )


@memo_bp.post("/api/share", name="memo.api_share")
async def api_share_memo(request: Request):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        ShareMemoRequest,
        error_message="共有するメモを指定してください。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    share_options, options_error = validate_payload_model(
        data,
        MemoShareCreateRequest,
        error_message="共有リンク設定が不正です。",
        status="fail",
    )
    if options_error is not None:
        return options_error

    try:
        share_state = await run_blocking(
            create_or_get_shared_memo_token,
            payload.memo_id,
            user_id,
            force_refresh=share_options.force_refresh,
            expires_in_days=share_options.expires_in_days,
        )
        return jsonify(_share_payload(share_state))
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(
            logger,
            "Failed to create share link for memo entry.",
            status="fail",
        )


@memo_bp.get("/api/shared", name="memo.api_shared")
async def api_shared_memo(request: Request):
    token = request.query_params.get("token", "").strip()
    if not token:
        return jsonify({"error": ERROR_TOKEN_REQUIRED}, status_code=400)

    try:
        payload_result = await run_blocking(get_shared_memo_payload, token)
        if isinstance(payload_result, tuple) and len(payload_result) == 2:
            payload, status_code = payload_result
            return jsonify(payload, status_code=status_code)
        return jsonify(payload_result)
    except ApiServiceError as exc:
        return jsonify_service_error(exc)
    except Error:
        return log_and_internal_server_error(
            logger,
            "Failed to load shared memo payload.",
        )


@memo_bp.get("/api/{memo_id:int}", name="memo.api_detail")
async def api_memo_detail(request: Request, memo_id: int):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        memo = await run_blocking(_fetch_memo_detail, user_id, memo_id)
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to load memo detail.", status="fail")


@memo_bp.patch("/api/{memo_id:int}", name="memo.api_update")
async def api_update_memo(request: Request, memo_id: int):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data, error_response = await require_json_dict(request, status="fail")
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        MemoUpdateRequest,
        error_message="更新データが不正です。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    if (
        payload.title is None
        and payload.tags is None
        and payload.input_content is None
        and payload.ai_response is None
    ):
        return jsonify({"status": "fail", "error": "更新する項目を指定してください。"}, status_code=400)

    try:
        memo = await run_blocking(
            _update_memo,
            user_id,
            memo_id,
            title=payload.title,
            tags=payload.tags,
            input_content=payload.input_content,
            ai_response=payload.ai_response,
        )
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to update memo entry.", status="fail")


@memo_bp.delete("/api/{memo_id:int}", name="memo.api_delete")
async def api_delete_memo(request: Request, memo_id: int):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        await run_blocking(_delete_memo, user_id, memo_id)
        return jsonify({"status": "success"})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to delete memo entry.", status="fail")


@memo_bp.post("/api/{memo_id:int}/archive", name="memo.api_archive")
async def api_archive_memo(request: Request, memo_id: int):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data = await get_json(request)
    if not isinstance(data, dict):
        data = {}

    payload, validation_error = validate_payload_model(
        data,
        MemoToggleRequest,
        error_message="アーカイブ設定が不正です。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        memo = await run_blocking(_set_memo_archive_state, user_id, memo_id, payload.enabled)
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to archive memo entry.", status="fail")


@memo_bp.post("/api/{memo_id:int}/pin", name="memo.api_pin")
async def api_pin_memo(request: Request, memo_id: int):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data = await get_json(request)
    if not isinstance(data, dict):
        data = {}

    payload, validation_error = validate_payload_model(
        data,
        MemoToggleRequest,
        error_message="ピン留め設定が不正です。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        memo = await run_blocking(_set_memo_pin_state, user_id, memo_id, payload.enabled)
        return jsonify({"status": "success", "memo": memo})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to pin memo entry.", status="fail")


@memo_bp.get("/api/{memo_id:int}/share", name="memo.api_share_detail")
async def api_memo_share_detail(request: Request, memo_id: int):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        share_state = await run_blocking(get_memo_share_state, memo_id, user_id)
        return jsonify(_share_payload(share_state))
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(
            logger,
            "Failed to load memo share status.",
            status="fail",
        )


@memo_bp.post("/api/{memo_id:int}/share", name="memo.api_share_refresh")
async def api_memo_share_refresh(request: Request, memo_id: int):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    data = await get_json(request)
    if not isinstance(data, dict):
        data = {}

    payload, validation_error = validate_payload_model(
        data,
        MemoShareCreateRequest,
        error_message="共有リンク設定が不正です。",
        status="fail",
    )
    if validation_error is not None:
        return validation_error

    try:
        share_state = await run_blocking(
            create_or_get_shared_memo_token,
            memo_id,
            user_id,
            force_refresh=payload.force_refresh,
            expires_in_days=payload.expires_in_days,
        )
        return jsonify(_share_payload(share_state))
    except ApiServiceError as exc:
        if exc.message == ERROR_MEMO_NOT_FOUND_FOR_SHARE:
            return jsonify_service_error(exc, status="fail")
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(
            logger,
            "Failed to refresh memo share status.",
            status="fail",
        )


@memo_bp.post("/api/{memo_id:int}/share/revoke", name="memo.api_share_revoke")
async def api_memo_share_revoke(request: Request, memo_id: int):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        share_state = await run_blocking(revoke_shared_memo_token, memo_id, user_id)
        return jsonify(_share_payload(share_state))
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(
            logger,
            "Failed to revoke memo share link.",
            status="fail",
        )


@memo_bp.api_route("", methods=["GET", "POST"], name="memo.create_memo")
async def create_memo(request: Request):
    status_code = 302 if request.method == "GET" else 303
    return redirect_to_frontend(request, status_code=status_code)
