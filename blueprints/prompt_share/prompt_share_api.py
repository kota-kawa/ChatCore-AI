# prompt_share/prompt_share_api.py
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from services.async_utils import run_blocking
from services.csrf import require_csrf
from services.db import get_db_connection
from services.request_models import (
    BookmarkCreateRequest,
    BookmarkDeleteRequest,
    PromptListEntryCreateRequest,
    SharedPromptCreateRequest,
)
from services.web import (
    jsonify,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

prompt_share_api_bp = APIRouter(prefix="/prompt_share/api", dependencies=[Depends(require_csrf)])
logger = logging.getLogger(__name__)


def _extract_id(row: dict[str, Any] | tuple[Any, ...] | None) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get("id")
    return row[0]


def _get_prompts_with_flags(user_id: int | None) -> list[dict[str, Any]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, title, category, content, author, input_examples, output_examples, created_at
            FROM prompts
            WHERE is_public = TRUE
              AND deleted_at IS NULL
            ORDER BY created_at DESC
            """
        )
        prompts = [dict(row) for row in cursor.fetchall()]

        bookmark_titles = set()
        saved_prompt_ids = set()
        if user_id:
            cursor.execute(
                """
                SELECT name
                  FROM task_with_examples
                 WHERE user_id = %s
                   AND deleted_at IS NULL
                """,
                (user_id,),
            )
            bookmarks = cursor.fetchall()
            bookmark_titles = {bookmark["name"] for bookmark in bookmarks}

            cursor.execute(
                """
                SELECT prompt_id
                FROM prompt_list_entries
                WHERE user_id = %s
                """,
                (user_id,),
            )
            saved_entries = cursor.fetchall()
            for entry in saved_entries:
                if entry["prompt_id"] is not None:
                    saved_prompt_ids.add(entry["prompt_id"])

        for prompt in prompts:
            created_at = prompt.get("created_at")
            if created_at is not None and hasattr(created_at, "isoformat"):
                prompt["created_at"] = created_at.isoformat()
            prompt["bookmarked"] = prompt["title"] in bookmark_titles
            prompt["saved_to_list"] = prompt["id"] in saved_prompt_ids
        return prompts
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _create_prompt_for_user(
    user_id: int,
    title: str,
    category: str,
    content: str,
    author: str,
    input_examples: str,
    output_examples: str,
) -> Any:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            INSERT INTO prompts (
                title,
                category,
                content,
                author,
                input_examples,
                output_examples,
                user_id,
                is_public,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())
            RETURNING id
        """
        cursor.execute(
            query,
            (title, category, content, author, input_examples, output_examples, user_id),
        )
        conn.commit()
        return _extract_id(cursor.fetchone())
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _add_bookmark_for_user(
    user_id: int,
    title: str,
    content: str,
    input_examples: str,
    output_examples: str,
) -> tuple[dict[str, Any], int]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id
              FROM task_with_examples
             WHERE user_id = %s
               AND name = %s
               AND deleted_at IS NULL
            """,
            (user_id, title),
        )
        existing = cursor.fetchone()
        if existing:
            return {"message": "すでに保存されています。", "saved_id": existing["id"]}, 200

        cursor.execute(
            """
            INSERT INTO task_with_examples
                (user_id, name, prompt_template, input_examples, output_examples)
            VALUES (%s,      %s,   %s,               %s,             %s)
            RETURNING id
            """,
            (user_id, title, content, input_examples, output_examples),
        )
        conn.commit()
        saved_id = _extract_id(cursor.fetchone())
        return {"message": "ブックマークが保存されました。", "saved_id": saved_id}, 201
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _remove_bookmark_for_user(user_id: int, title: str) -> None:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE task_with_examples
               SET deleted_at = CURRENT_TIMESTAMP
             WHERE user_id = %s
               AND name = %s
               AND deleted_at IS NULL
            """,
            (user_id, title),
        )
        conn.commit()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _add_prompt_list_entry_for_user(
    user_id: int,
    prompt_id: int,
) -> tuple[dict[str, Any], int]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id
            FROM prompts
            WHERE id = %s
              AND is_public = TRUE
              AND deleted_at IS NULL
            """,
            (prompt_id,),
        )
        prompt = cursor.fetchone()
        if not prompt:
            return {"error": "対象の公開プロンプトが見つかりませんでした。"}, 404

        cursor.execute(
            """
            SELECT id
            FROM prompt_list_entries
            WHERE user_id = %s AND prompt_id = %s
            """,
            (user_id, prompt_id),
        )
        existing = cursor.fetchone()
        if existing:
            return {"message": "すでに保存されています。", "saved_id": existing["id"]}, 200

        cursor.execute(
            """
            INSERT INTO prompt_list_entries
                (user_id, prompt_id)
            VALUES (%s, %s)
            RETURNING id
            """,
            (user_id, prompt_id),
        )
        conn.commit()
        saved_id = _extract_id(cursor.fetchone())
        return {"message": "プロンプトリストに保存しました。", "saved_id": saved_id}, 201
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@prompt_share_api_bp.get("/prompts", name="prompt_share_api.get_prompts")
async def get_prompts(request: Request):
    """保存されている全プロンプトを取得するエンドポイント"""
    session = getattr(request, "session", {}) or {}
    user_id = session.get("user_id")
    try:
        prompts = await run_blocking(_get_prompts_with_flags, user_id)
        return jsonify({"prompts": prompts})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to load shared prompts.",
        )


@prompt_share_api_bp.post("/prompts", name="prompt_share_api.create_prompt")
async def create_prompt(request: Request):
    """新しいプロンプトを投稿するエンドポイント"""
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]

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

    try:
        prompt_id = await run_blocking(
            _create_prompt_for_user,
            user_id,
            payload.title,
            payload.category,
            payload.content,
            payload.author,
            payload.input_examples,
            payload.output_examples,
        )
        return jsonify({"message": "プロンプトが作成されました。", "prompt_id": prompt_id}, status_code=201)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to create shared prompt.",
        )


@prompt_share_api_bp.post("/bookmark", name="prompt_share_api.add_bookmark")
async def add_bookmark(request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]

    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    request_payload, validation_error = validate_payload_model(
        data,
        BookmarkCreateRequest,
        error_message="必要なフィールドが不足しています",
    )
    if validation_error is not None:
        return validation_error

    try:
        response_payload, status_code = await run_blocking(
            _add_bookmark_for_user,
            user_id,
            request_payload.title,
            request_payload.content,
            request_payload.input_examples,
            request_payload.output_examples,
        )
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to add bookmark.",
        )


@prompt_share_api_bp.delete("/bookmark", name="prompt_share_api.remove_bookmark")
async def remove_bookmark(request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]

    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    request_payload, validation_error = validate_payload_model(
        data,
        BookmarkDeleteRequest,
        error_message="必要なフィールドが不足しています",
    )
    if validation_error is not None:
        return validation_error

    try:
        await run_blocking(_remove_bookmark_for_user, user_id, request_payload.title)
        return jsonify({"message": "ブックマークが削除されました。"})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to remove bookmark.",
        )


@prompt_share_api_bp.post("/prompt_list", name="prompt_share_api.add_prompt_to_list")
async def add_prompt_to_list(request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]

    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    request_payload, validation_error = validate_payload_model(
        data,
        PromptListEntryCreateRequest,
        error_message="必要なフィールドが不足しています",
    )
    if validation_error is not None:
        return validation_error

    try:
        response_payload, status_code = await run_blocking(
            _add_prompt_list_entry_for_user,
            user_id,
            request_payload.prompt_id,
        )
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to add prompt to prompt list.",
        )
