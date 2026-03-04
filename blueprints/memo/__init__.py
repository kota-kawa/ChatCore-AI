from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from services.request_models import MemoCreateRequest
from services.async_utils import run_blocking
from services.csrf import require_csrf
from services.db import Error, get_db_connection
from services.web import (
    flash,
    get_json,
    jsonify,
    log_and_internal_server_error,
    redirect_to_frontend,
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


def _fetch_recent_memos(limit: int = 10) -> list[dict[str, Any]]:
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
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
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
            INSERT INTO memo_entries (input_content, ai_response, title, tags)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (input_content, ai_response, resolved_title, tags or None),
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
    safe_limit = max(1, min(limit, 100))
    recent_memos = await run_blocking(_fetch_recent_memos, safe_limit)
    memos = [_serialize_memo(memo) for memo in recent_memos]
    return jsonify({"memos": memos})


@memo_bp.post("/api", name="memo.api_create")
async def api_create_memo(request: Request):
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


@memo_bp.api_route("", methods=["GET", "POST"], name="memo.create_memo")
async def create_memo(request: Request):
    status_code = 302 if request.method == "GET" else 303
    return redirect_to_frontend(request, status_code=status_code)
