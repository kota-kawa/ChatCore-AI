from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from services.request_models import MemoCreateRequest
from services.async_utils import run_blocking
from services.csrf import require_csrf
from services.db import Error, get_db_connection
from services.memo_share import create_or_get_shared_memo_token, get_shared_memo_payload
from services.request_models import ShareMemoRequest
from services.web import (
    flash,
    frontend_url,
    get_json,
    jsonify,
    log_and_internal_server_error,
    redirect_to_frontend,
    require_json_dict,
    validate_payload_model,
)

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


def _fetch_recent_memos(user_id: int, limit: int = 10) -> list[dict[str, Any]]:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                id,
                title,
                tags,
                created_at,
                input_content,
                ai_response
            FROM memo_entries
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        return list(cursor.fetchall())
    except Error:
        return []
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def _serialize_memo(memo: dict[str, Any]) -> dict[str, Any]:
    created_at = memo.get("created_at")
    created_at_str = created_at.strftime("%Y-%m-%d %H:%M") if created_at else None
    return {
        "id": memo.get("id"),
        "title": memo.get("title"),
        "tags": memo.get("tags"),
        "created_at": created_at_str,
        "input_content": memo.get("input_content") or "",
        "ai_response": memo.get("ai_response") or "",
    }


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


@memo_bp.get("/api/recent", name="memo.api_recent")
async def api_recent_memos(request: Request, limit: int = 10):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": "ログインが必要です"}, status_code=401)

    safe_limit = max(1, min(limit, 100))
    recent_memos = await run_blocking(_fetch_recent_memos, user_id, safe_limit)
    memos = [_serialize_memo(memo) for memo in recent_memos]
    return jsonify({"memos": memos})


@memo_bp.post("/api", name="memo.api_create")
async def api_create_memo(request: Request):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": "ログインが必要です"}, status_code=401)

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
        return jsonify({"status": "fail", "error": "ログインが必要です"}, status_code=401)

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

    try:
        share_token, status_code = await run_blocking(
            create_or_get_shared_memo_token,
            payload.memo_id,
            user_id,
        )
        if status_code == 404 or not share_token:
            return jsonify(
                {"status": "fail", "error": "共有対象のメモが見つかりません。"},
                status_code=404,
            )

        share_url = frontend_url(f"/shared/memo/{share_token}")
        return jsonify(
            {
                "status": "success",
                "share_token": share_token,
                "share_url": share_url,
            }
        )
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
        return jsonify({"error": "token is required"}, status_code=400)

    try:
        payload, status_code = await run_blocking(get_shared_memo_payload, token)
        return jsonify(payload, status_code=status_code)
    except Error:
        return log_and_internal_server_error(
            logger,
            "Failed to load shared memo payload.",
        )


@memo_bp.api_route("", methods=["GET", "POST"], name="memo.create_memo")
async def create_memo(request: Request):
    status_code = 302 if request.method == "GET" else 303
    return redirect_to_frontend(request, status_code=status_code)
