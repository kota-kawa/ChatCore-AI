# prompt_manage_api.py
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from services.async_utils import run_blocking
from services.csrf import require_csrf
from services.db import get_db_connection
from services.request_models import PromptUpdateRequest
from services.web import (
    jsonify,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

prompt_manage_api_bp = APIRouter(prefix="/prompt_manage/api", dependencies=[Depends(require_csrf)])
logger = logging.getLogger(__name__)


def _serialize_prompt_list_entry(row: dict[str, Any]) -> dict[str, Any]:
    prompt_created_at = row.get("prompt_created_at")
    saved_at = row.get("saved_at")
    return {
        "id": row.get("entry_id"),
        "prompt_id": row.get("prompt_id"),
        "created_at": saved_at.isoformat() if hasattr(saved_at, "isoformat") else saved_at,
        "prompt": {
            "id": row.get("prompt_id"),
            "title": row.get("title"),
            "category": row.get("category"),
            "content": row.get("content"),
            "author": row.get("author"),
            "input_examples": row.get("input_examples"),
            "output_examples": row.get("output_examples"),
            "created_at": (
                prompt_created_at.isoformat()
                if hasattr(prompt_created_at, "isoformat")
                else prompt_created_at
            ),
        },
    }


def _fetch_my_prompts(user_id: int) -> list[dict[str, Any]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT id, title, category, content, input_examples, output_examples, created_at
            FROM prompts
            WHERE user_id = %s
              AND deleted_at IS NULL
            ORDER BY created_at DESC
        """
        cursor.execute(query, (user_id,))
        return cursor.fetchall()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _fetch_saved_prompts(user_id: int) -> list[dict[str, Any]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT id,
                   name,
                   prompt_template,
                   response_rules,
                   output_skeleton,
                   input_examples,
                   output_examples,
                   created_at
            FROM task_with_examples
            WHERE user_id = %s
              AND deleted_at IS NULL
            ORDER BY created_at DESC, id DESC
        """
        cursor.execute(query, (user_id,))
        return cursor.fetchall()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _fetch_prompt_list(user_id: int) -> list[dict[str, Any]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT ple.id AS entry_id,
                   ple.prompt_id,
                   p.title,
                   p.category,
                   p.content,
                   p.author,
                   p.input_examples,
                   p.output_examples,
                   p.created_at AS prompt_created_at,
                   ple.created_at AS saved_at
            FROM prompt_list_entries ple
            JOIN prompts p ON p.id = ple.prompt_id
                          AND p.deleted_at IS NULL
            WHERE ple.user_id = %s
            ORDER BY ple.created_at DESC, ple.id DESC
        """
        cursor.execute(query, (user_id,))
        return [_serialize_prompt_list_entry(dict(row)) for row in cursor.fetchall()]
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _delete_prompt_list_entry_for_user(user_id: int, entry_id: int) -> int:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "DELETE FROM prompt_list_entries WHERE id = %s AND user_id = %s"
        cursor.execute(query, (entry_id, user_id))
        conn.commit()
        return cursor.rowcount
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _delete_saved_prompt_for_user(user_id: int, prompt_id: int) -> int:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            UPDATE task_with_examples
               SET deleted_at = CURRENT_TIMESTAMP
             WHERE id = %s
               AND user_id = %s
               AND deleted_at IS NULL
        """
        cursor.execute(query, (prompt_id, user_id))
        conn.commit()
        return cursor.rowcount
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _update_prompt_for_user(
    user_id: int,
    prompt_id: int,
    title: str,
    category: str,
    content: str,
    input_examples: str,
    output_examples: str,
) -> int:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            UPDATE prompts
            SET title = %s, category = %s, content = %s, input_examples = %s, output_examples = %s
            WHERE id = %s
              AND user_id = %s
              AND deleted_at IS NULL
        """
        cursor.execute(
            query,
            (
                title,
                category,
                content,
                input_examples,
                output_examples,
                prompt_id,
                user_id,
            ),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _delete_prompt_for_user(user_id: int, prompt_id: int) -> int:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            UPDATE prompts
               SET deleted_at = CURRENT_TIMESTAMP
             WHERE id = %s
               AND user_id = %s
               AND deleted_at IS NULL
        """
        cursor.execute(query, (prompt_id, user_id))
        conn.commit()
        return cursor.rowcount
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@prompt_manage_api_bp.get("/my_prompts", name="prompt_manage_api.get_my_prompts")
async def get_my_prompts(request: Request):
    """ログインユーザーが投稿したプロンプト一覧を取得するエンドポイント"""
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]
    try:
        prompts = await run_blocking(_fetch_my_prompts, user_id)
        return jsonify({"prompts": prompts})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to load my prompts.",
        )


@prompt_manage_api_bp.get("/saved_prompts", name="prompt_manage_api.get_saved_prompts")
async def get_saved_prompts(request: Request):
    """ログインユーザーが保存したプロンプト（ブックマーク）一覧を取得するエンドポイント"""
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)

    user_id = request.session["user_id"]
    try:
        prompts = await run_blocking(_fetch_saved_prompts, user_id)
        return jsonify({"prompts": prompts})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to load saved prompts.",
        )


@prompt_manage_api_bp.get("/prompt_list", name="prompt_manage_api.get_prompt_list")
async def get_prompt_list(request: Request):
    """ログインユーザーのプロンプトリストを取得するエンドポイント"""
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)

    user_id = request.session["user_id"]
    try:
        prompts = await run_blocking(_fetch_prompt_list, user_id)
        return jsonify({"prompts": prompts})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to load prompt list.",
        )


@prompt_manage_api_bp.delete(
    "/prompt_list/{entry_id}", name="prompt_manage_api.delete_prompt_list_entry"
)
async def delete_prompt_list_entry(entry_id: int, request: Request):
    """プロンプトリストからエントリを削除するエンドポイント"""
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)

    user_id = request.session["user_id"]
    try:
        deleted = await run_blocking(_delete_prompt_list_entry_for_user, user_id, entry_id)
        if deleted == 0:
            return jsonify({"error": "対象のプロンプトが見つかりませんでした。"}, status_code=404)
        return jsonify({"message": "プロンプトを削除しました。"})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to delete prompt list entry.",
        )


@prompt_manage_api_bp.delete(
    "/saved_prompts/{prompt_id}", name="prompt_manage_api.delete_saved_prompt"
)
async def delete_saved_prompt(prompt_id: int, request: Request):
    """保存したプロンプトを削除するエンドポイント"""
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)

    user_id = request.session["user_id"]
    try:
        deleted = await run_blocking(_delete_saved_prompt_for_user, user_id, prompt_id)
        if deleted == 0:
            return jsonify({"error": "対象の保存済みプロンプトが見つかりませんでした。"}, status_code=404)
        return jsonify({"message": "保存したプロンプトを削除しました。"})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to delete saved prompt.",
        )


@prompt_manage_api_bp.put("/prompts/{prompt_id}", name="prompt_manage_api.update_prompt")
async def update_prompt(prompt_id: int, request: Request):
    """投稿済みプロンプトの内容を更新するエンドポイント"""
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    payload, validation_error = validate_payload_model(
        data,
        PromptUpdateRequest,
        error_message="必要なフィールドが不足しています。",
    )
    if validation_error is not None:
        return validation_error

    try:
        updated = await run_blocking(
            _update_prompt_for_user,
            user_id,
            prompt_id,
            payload.title,
            payload.category,
            payload.content,
            payload.input_examples,
            payload.output_examples,
        )
        if updated == 0:
            return jsonify({"error": "対象のプロンプトが見つかりませんでした。"}, status_code=404)
        return jsonify({"message": "プロンプトが更新されました。"})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to update prompt.",
        )


@prompt_manage_api_bp.delete("/prompts/{prompt_id}", name="prompt_manage_api.delete_prompt")
async def delete_prompt(prompt_id: int, request: Request):
    """投稿済みプロンプトを削除するエンドポイント"""
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]

    try:
        deleted = await run_blocking(_delete_prompt_for_user, user_id, prompt_id)
        if deleted == 0:
            return jsonify({"error": "対象のプロンプトが見つかりませんでした。"}, status_code=404)
        return jsonify({"message": "プロンプトが削除されました。"})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to delete prompt.",
        )
