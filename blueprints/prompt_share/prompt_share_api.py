# prompt_share/prompt_share_api.py
import logging
import os
from uuid import uuid4
from typing import Any

from fastapi import APIRouter, Depends, Request
from werkzeug.utils import secure_filename

from services.async_utils import run_blocking
from services.csrf import require_csrf
from services.db import get_db_connection
from services.request_models import (
    BookmarkCreateRequest,
    BookmarkDeleteRequest,
    PromptLikeRequest,
    PromptListEntryCreateRequest,
    SharedPromptCreateRequest,
)
from services.web import (
    BASE_DIR,
    jsonify,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

prompt_share_api_bp = APIRouter(prefix="/prompt_share/api", dependencies=[Depends(require_csrf)])
logger = logging.getLogger(__name__)
PROMPT_TYPE_TEXT = "text"
PROMPT_TYPE_IMAGE = "image"
PROMPT_IMAGE_UPLOAD_DIR = os.path.join(
    BASE_DIR,
    "frontend",
    "public",
    "static",
    "uploads",
    "prompt_share",
)
PROMPT_IMAGE_URL_PREFIX = "/static/uploads/prompt_share"
PROMPT_IMAGE_MAX_BYTES = 5 * 1024 * 1024
PROMPT_IMAGE_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _extract_id(row: dict[str, Any] | tuple[Any, ...] | None) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get("id")
    return row[0]


def _normalize_prompt_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {PROMPT_TYPE_IMAGE, "image_prompt", "image-generation", "image_generation"}:
        return PROMPT_TYPE_IMAGE
    return PROMPT_TYPE_TEXT


def _serialize_prompt_row(row: dict[str, Any]) -> dict[str, Any]:
    prompt = dict(row)
    created_at = prompt.get("created_at")
    if created_at is not None and hasattr(created_at, "isoformat"):
        prompt["created_at"] = created_at.isoformat()
    prompt["prompt_type"] = _normalize_prompt_type(prompt.get("prompt_type"))
    prompt["reference_image_url"] = prompt.get("reference_image_url") or None
    return prompt


def _delete_prompt_reference_image(image_url: str | None) -> None:
    if not image_url or not image_url.startswith(f"{PROMPT_IMAGE_URL_PREFIX}/"):
        return
    filename = image_url.rsplit("/", 1)[-1].strip()
    if not filename:
        return
    filepath = os.path.join(PROMPT_IMAGE_UPLOAD_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)


def _save_prompt_reference_image(upload_file: Any, user_id: int) -> str:
    filename = secure_filename(getattr(upload_file, "filename", "") or "")
    if not filename:
        raise ValueError("画像ファイル名が不正です。")

    extension = os.path.splitext(filename)[1].lower()
    if extension not in PROMPT_IMAGE_ALLOWED_EXTENSIONS:
        raise ValueError("画像は PNG / JPG / WebP / GIF のいずれかを指定してください。")

    content_type = str(getattr(upload_file, "content_type", "") or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise ValueError("画像ファイルのみアップロードできます。")

    os.makedirs(PROMPT_IMAGE_UPLOAD_DIR, exist_ok=True)
    stored_filename = f"user_{user_id}_{uuid4().hex}{extension}"
    filepath = os.path.join(PROMPT_IMAGE_UPLOAD_DIR, stored_filename)
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
                if total_size > PROMPT_IMAGE_MAX_BYTES:
                    raise ValueError("画像サイズは5MB以下にしてください。")
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

    return f"{PROMPT_IMAGE_URL_PREFIX}/{stored_filename}"


def _get_prompts_with_flags(user_id: int | None) -> list[dict[str, Any]]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                p.id,
                p.title,
                p.category,
                p.content,
                p.author,
                p.input_examples,
                p.output_examples,
                p.ai_model,
                p.prompt_type,
                p.reference_image_url,
                p.created_at,
                CASE WHEN pl.id IS NOT NULL THEN TRUE ELSE FALSE END AS liked,
                CASE WHEN b.id IS NOT NULL THEN TRUE ELSE FALSE END AS bookmarked,
                CASE WHEN ple.id IS NOT NULL THEN TRUE ELSE FALSE END AS saved_to_list
            FROM prompts AS p
            LEFT JOIN prompt_likes AS pl
              ON pl.user_id = %s
             AND pl.prompt_id = p.id
            LEFT JOIN task_with_examples AS b
              ON b.user_id = %s
             AND b.name = p.title
             AND b.deleted_at IS NULL
            LEFT JOIN prompt_list_entries AS ple
              ON ple.user_id = %s
             AND ple.prompt_id = p.id
            WHERE p.is_public = TRUE
              AND p.deleted_at IS NULL
            ORDER BY p.created_at DESC
            """,
            (user_id, user_id, user_id),
        )
        prompts = []
        for row in cursor.fetchall():
            prompt = _serialize_prompt_row(dict(row))
            prompt["liked"] = bool(prompt.get("liked"))
            prompt["bookmarked"] = bool(prompt.get("bookmarked"))
            prompt["saved_to_list"] = bool(prompt.get("saved_to_list"))
            prompts.append(prompt)
        return prompts
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _get_public_prompt_by_id(prompt_id: int) -> dict[str, Any] | None:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                id,
                title,
                category,
                content,
                author,
                input_examples,
                output_examples,
                ai_model,
                prompt_type,
                reference_image_url,
                created_at
            FROM prompts
            WHERE id = %s
              AND is_public = TRUE
              AND deleted_at IS NULL
            LIMIT 1
            """,
            (prompt_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return _serialize_prompt_row(dict(row))
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
    prompt_type: str,
    input_examples: str,
    output_examples: str,
    ai_model: str,
    reference_image_url: str | None,
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
                prompt_type,
                reference_image_url,
                input_examples,
                output_examples,
                ai_model,
                user_id,
                is_public,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())
            RETURNING id
        """
        cursor.execute(
            query,
            (
                title,
                category,
                content,
                author,
                _normalize_prompt_type(prompt_type),
                reference_image_url,
                input_examples,
                output_examples,
                ai_model or None,
                user_id,
            ),
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


def _add_prompt_like_for_user(
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
            INSERT INTO prompt_likes (user_id, prompt_id)
            VALUES (%s, %s)
            ON CONFLICT (user_id, prompt_id) DO NOTHING
            RETURNING id
            """,
            (user_id, prompt_id),
        )
        inserted = cursor.fetchone()
        conn.commit()
        if inserted:
            return {"message": "いいねしました。", "liked": True}, 201
        return {"message": "すでにいいねしています。", "liked": True}, 200
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _remove_prompt_like_for_user(user_id: int, prompt_id: int) -> int:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM prompt_likes
            WHERE user_id = %s
              AND prompt_id = %s
            """,
            (user_id, prompt_id),
        )
        conn.commit()
        return cursor.rowcount
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
        return jsonify({"status": "success", "prompts": prompts})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to load shared prompts.",
        )


@prompt_share_api_bp.get("/prompts/{prompt_id}", name="prompt_share_api.get_prompt_detail")
async def get_prompt_detail(prompt_id: int):
    try:
        prompt = await run_blocking(_get_public_prompt_by_id, prompt_id)
        if not prompt:
            return jsonify({"error": "プロンプトが見つかりません"}, status_code=404)
        return jsonify({"status": "success", "prompt": prompt})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to load public prompt detail.",
        )


@prompt_share_api_bp.post("/prompts", name="prompt_share_api.create_prompt")
async def create_prompt(request: Request):
    """新しいプロンプトを投稿するエンドポイント"""
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]

    content_type = request.headers.get("content-type", "")
    image_file = None
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        image_candidate = form.get("reference_image")
        image_file = image_candidate if getattr(image_candidate, "filename", "") else None
        data = {
            "title": form.get("title", ""),
            "category": form.get("category", ""),
            "content": form.get("content", ""),
            "author": form.get("author", ""),
            "prompt_type": form.get("prompt_type", PROMPT_TYPE_TEXT),
            "input_examples": form.get("input_examples", ""),
            "output_examples": form.get("output_examples", ""),
            "ai_model": form.get("ai_model", ""),
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

    normalized_prompt_type = _normalize_prompt_type(payload.prompt_type)
    if normalized_prompt_type != PROMPT_TYPE_IMAGE and image_file is not None:
        return jsonify(
            {"error": "画像は画像生成プロンプトでのみアップロードできます。"},
            status_code=400,
        )

    reference_image_url = None
    try:
        if image_file is not None:
            reference_image_url = await run_blocking(_save_prompt_reference_image, image_file, user_id)
        prompt_id = await run_blocking(
            _create_prompt_for_user,
            user_id,
            payload.title,
            payload.category,
            payload.content,
            payload.author,
            normalized_prompt_type,
            payload.input_examples,
            payload.output_examples,
            payload.ai_model,
            reference_image_url,
        )
        return jsonify({"message": "プロンプトが作成されました。", "prompt_id": prompt_id}, status_code=201)
    except ValueError as exc:
        if reference_image_url:
            await run_blocking(_delete_prompt_reference_image, reference_image_url)
        return jsonify({"error": str(exc)}, status_code=400)
    except Exception:
        if reference_image_url:
            await run_blocking(_delete_prompt_reference_image, reference_image_url)
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


@prompt_share_api_bp.post("/like", name="prompt_share_api.add_like")
async def add_like(request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]

    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    request_payload, validation_error = validate_payload_model(
        data,
        PromptLikeRequest,
        error_message="必要なフィールドが不足しています",
    )
    if validation_error is not None:
        return validation_error

    try:
        response_payload, status_code = await run_blocking(
            _add_prompt_like_for_user,
            user_id,
            request_payload.prompt_id,
        )
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to add prompt like.",
        )


@prompt_share_api_bp.delete("/like", name="prompt_share_api.remove_like")
async def remove_like(request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]

    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    request_payload, validation_error = validate_payload_model(
        data,
        PromptLikeRequest,
        error_message="必要なフィールドが不足しています",
    )
    if validation_error is not None:
        return validation_error

    try:
        await run_blocking(_remove_prompt_like_for_user, user_id, request_payload.prompt_id)
        return jsonify({"message": "いいねを解除しました。", "liked": False})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to remove prompt like.",
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
