# prompt_share/prompt_share_api.py
import logging
import os
import re
from uuid import uuid4
from typing import Any

from fastapi import APIRouter, Depends, Request
from werkzeug.utils import secure_filename

from services.async_utils import run_blocking
from services.auth_limits import consume_rate_limit, get_request_client_ip
from services.csrf import require_csrf
from services.db import get_db_connection
from services.request_models import (
    BookmarkCreateRequest,
    BookmarkDeleteRequest,
    PromptCommentCreateRequest,
    PromptCommentReportRequest,
    PromptLikeRequest,
    PromptListEntryCreateRequest,
    SharedPromptCreateRequest,
)
from services.web import (
    BASE_DIR,
    jsonify,
    jsonify_rate_limited,
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
PROMPT_COMMENT_RATE_WINDOW_SECONDS = 300
PROMPT_COMMENT_PER_IP_LIMIT = 20
PROMPT_COMMENT_PER_USER_LIMIT = 12
PROMPT_COMMENT_COOLDOWN_SECONDS = 10
PROMPT_COMMENT_DUPLICATE_WINDOW_SECONDS = 60
PROMPT_COMMENT_LIST_LIMIT = 200
PROMPT_COMMENT_AUTO_HIDE_REPORT_THRESHOLD = 3
PROMPT_COMMENT_MAX_URLS = 3
PROMPT_COMMENT_LINK_PATTERN = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)


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
    prompt["comment_count"] = int(prompt.get("comment_count") or 0)
    return prompt


def _serialize_prompt_comment_row(row: dict[str, Any], actor_user_id: int | None) -> dict[str, Any]:
    created_at = row.get("created_at")
    user_id = row.get("user_id")
    prompt_owner_id = row.get("prompt_owner_id")
    actor_is_admin = bool(row.get("actor_is_admin"))
    mine = actor_user_id is not None and user_id == actor_user_id
    can_delete = bool(
        actor_is_admin
        or mine
        or (actor_user_id is not None and prompt_owner_id == actor_user_id)
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


def _consume_prompt_comment_create_limits(
    request: Request,
    user_id: int,
) -> tuple[bool, str | None, int | None]:
    client_ip = get_request_client_ip(request)

    allowed, _, retry_after = consume_rate_limit(
        "prompt_comment:create:ip",
        client_ip,
        limit=PROMPT_COMMENT_PER_IP_LIMIT,
        window_seconds=PROMPT_COMMENT_RATE_WINDOW_SECONDS,
    )
    if not allowed:
        return (
            False,
            (
                "コメント投稿の試行回数が多すぎます。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
            retry_after,
        )

    allowed, _, retry_after = consume_rate_limit(
        "prompt_comment:create:user",
        str(user_id),
        limit=PROMPT_COMMENT_PER_USER_LIMIT,
        window_seconds=PROMPT_COMMENT_RATE_WINDOW_SECONDS,
    )
    if not allowed:
        return (
            False,
            (
                "コメント投稿の試行回数が多すぎます。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
            retry_after,
        )

    allowed, _, retry_after = consume_rate_limit(
        "prompt_comment:create:cooldown",
        str(user_id),
        limit=1,
        window_seconds=PROMPT_COMMENT_COOLDOWN_SECONDS,
    )
    if not allowed:
        return (
            False,
            (
                "コメントは短時間に連続投稿できません。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
            retry_after,
        )

    return True, None, None


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
                COALESCE(pc.comment_count, 0) AS comment_count,
                CASE WHEN pl.id IS NOT NULL THEN TRUE ELSE FALSE END AS liked,
                CASE WHEN b.id IS NOT NULL THEN TRUE ELSE FALSE END AS bookmarked,
                CASE WHEN ple.id IS NOT NULL THEN TRUE ELSE FALSE END AS saved_to_list
            FROM prompts AS p
            LEFT JOIN (
                SELECT prompt_id, COUNT(*) AS comment_count
                FROM prompt_comments
                WHERE deleted_at IS NULL
                  AND hidden_by_reports_at IS NULL
                GROUP BY prompt_id
            ) AS pc
              ON pc.prompt_id = p.id
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
            prompt["comment_count"] = int(prompt.get("comment_count") or 0)
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
                (
                    SELECT COUNT(*)
                    FROM prompt_comments AS pc
                    WHERE pc.prompt_id = prompts.id
                      AND pc.deleted_at IS NULL
                      AND pc.hidden_by_reports_at IS NULL
                ) AS comment_count,
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


def _count_visible_prompt_comments(cursor: Any, prompt_id: int) -> int:
    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM prompt_comments
        WHERE prompt_id = %s
          AND deleted_at IS NULL
          AND hidden_by_reports_at IS NULL
        """,
        (prompt_id,),
    )
    row = cursor.fetchone() or {}
    if isinstance(row, dict):
        return int(row.get("total") or 0)
    return int(row[0] or 0)


def _fetch_prompt_comments(
    prompt_id: int,
    actor_user_id: int | None,
    actor_is_admin: bool,
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
            LIMIT 1
            """,
            (prompt_id,),
        )
        prompt = cursor.fetchone()
        if not prompt:
            return {"error": "対象の公開プロンプトが見つかりませんでした。"}, 404

        cursor.execute(
            """
            SELECT
                pc.id,
                pc.prompt_id,
                pc.user_id,
                COALESCE(u.username, 'ユーザー') AS author_name,
                pc.content,
                pc.created_at,
                p.user_id AS prompt_owner_id,
                %s AS actor_is_admin
            FROM prompt_comments AS pc
            JOIN prompts AS p
              ON p.id = pc.prompt_id
             AND p.deleted_at IS NULL
            JOIN users AS u
              ON u.id = pc.user_id
            WHERE pc.prompt_id = %s
              AND pc.deleted_at IS NULL
              AND pc.hidden_by_reports_at IS NULL
            ORDER BY pc.created_at ASC, pc.id ASC
            LIMIT %s
            """,
            (actor_is_admin, prompt_id, PROMPT_COMMENT_LIST_LIMIT),
        )
        comments = [
            _serialize_prompt_comment_row(dict(row), actor_user_id)
            for row in cursor.fetchall()
        ]
        comment_count = _count_visible_prompt_comments(cursor, prompt_id)
        return {"comments": comments, "comment_count": comment_count}, 200
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _add_prompt_comment_for_user(
    user_id: int,
    prompt_id: int,
    content: str,
    actor_is_admin: bool,
) -> tuple[dict[str, Any], int]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, user_id
            FROM prompts
            WHERE id = %s
              AND is_public = TRUE
              AND deleted_at IS NULL
            LIMIT 1
            """,
            (prompt_id,),
        )
        prompt = cursor.fetchone()
        if not prompt:
            return {"error": "対象の公開プロンプトが見つかりませんでした。"}, 404

        cursor.execute(
            """
            SELECT id
            FROM prompt_comments
            WHERE user_id = %s
              AND prompt_id = %s
              AND content = %s
              AND deleted_at IS NULL
              AND created_at >= (
                    CURRENT_TIMESTAMP - (%s * INTERVAL '1 second')
              )
            LIMIT 1
            """,
            (user_id, prompt_id, content, PROMPT_COMMENT_DUPLICATE_WINDOW_SECONDS),
        )
        duplicated = cursor.fetchone()
        if duplicated:
            return {"error": "同じ内容のコメントは時間をおいて投稿してください。"}, 409

        cursor.execute(
            """
            INSERT INTO prompt_comments (prompt_id, user_id, content)
            VALUES (%s, %s, %s)
            RETURNING id, prompt_id, user_id, content, created_at
            """,
            (prompt_id, user_id, content),
        )
        inserted = dict(cursor.fetchone() or {})
        cursor.execute(
            """
            SELECT COALESCE(username, 'ユーザー') AS username
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )
        user_row = cursor.fetchone() or {}
        inserted["author_name"] = user_row.get("username") or "ユーザー"
        inserted["prompt_owner_id"] = prompt.get("user_id")
        inserted["actor_is_admin"] = actor_is_admin
        comment = _serialize_prompt_comment_row(inserted, user_id)
        comment_count = _count_visible_prompt_comments(cursor, prompt_id)
        conn.commit()
        return (
            {
                "message": "コメントを投稿しました。",
                "comment": comment,
                "comment_count": comment_count,
            },
            201,
        )
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _delete_prompt_comment_for_actor(
    actor_user_id: int,
    comment_id: int,
    actor_is_admin: bool,
) -> tuple[dict[str, Any], int]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                pc.id,
                pc.prompt_id,
                pc.user_id,
                p.user_id AS prompt_owner_id
            FROM prompt_comments AS pc
            JOIN prompts AS p
              ON p.id = pc.prompt_id
             AND p.deleted_at IS NULL
            WHERE pc.id = %s
              AND pc.deleted_at IS NULL
            LIMIT 1
            """,
            (comment_id,),
        )
        comment = cursor.fetchone()
        if not comment:
            return {"error": "対象コメントが見つかりませんでした。"}, 404

        can_delete = actor_is_admin or actor_user_id in {
            comment.get("user_id"),
            comment.get("prompt_owner_id"),
        }
        if not can_delete:
            return {"error": "このコメントを削除する権限がありません。"}, 403

        cursor.execute(
            """
            UPDATE prompt_comments
            SET deleted_at = CURRENT_TIMESTAMP
            WHERE id = %s
              AND deleted_at IS NULL
            """,
            (comment_id,),
        )
        prompt_id = int(comment.get("prompt_id"))
        comment_count = _count_visible_prompt_comments(cursor, prompt_id)
        conn.commit()
        return (
            {
                "message": "コメントを削除しました。",
                "prompt_id": prompt_id,
                "comment_count": comment_count,
            },
            200,
        )
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def _report_prompt_comment_for_user(
    reporter_user_id: int,
    comment_id: int,
    reason: str,
    details: str,
) -> tuple[dict[str, Any], int]:
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                pc.id,
                pc.prompt_id,
                pc.user_id
            FROM prompt_comments AS pc
            JOIN prompts AS p
              ON p.id = pc.prompt_id
             AND p.deleted_at IS NULL
            WHERE pc.id = %s
              AND pc.deleted_at IS NULL
              AND pc.hidden_by_reports_at IS NULL
            LIMIT 1
            """,
            (comment_id,),
        )
        comment = cursor.fetchone()
        if not comment:
            return {"error": "対象コメントが見つかりませんでした。"}, 404
        if int(comment.get("user_id") or 0) == reporter_user_id:
            return {"error": "自分のコメントは報告できません。"}, 400

        cursor.execute(
            """
            INSERT INTO prompt_comment_reports (
                comment_id,
                reporter_user_id,
                reason,
                details
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (comment_id, reporter_user_id) DO NOTHING
            RETURNING id
            """,
            (comment_id, reporter_user_id, reason, details or None),
        )
        inserted = cursor.fetchone()
        if not inserted:
            conn.commit()
            return {"message": "このコメントはすでに報告済みです。", "already_reported": True}, 200

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM prompt_comment_reports
            WHERE comment_id = %s
            """,
            (comment_id,),
        )
        report_row = cursor.fetchone() or {}
        report_count = int(report_row.get("total") or 0)
        hidden = False
        if report_count >= PROMPT_COMMENT_AUTO_HIDE_REPORT_THRESHOLD:
            cursor.execute(
                """
                UPDATE prompt_comments
                SET hidden_by_reports_at = CURRENT_TIMESTAMP,
                    hidden_reason = 'reported'
                WHERE id = %s
                  AND hidden_by_reports_at IS NULL
                """,
                (comment_id,),
            )
            hidden = cursor.rowcount > 0

        prompt_id = int(comment.get("prompt_id"))
        comment_count = _count_visible_prompt_comments(cursor, prompt_id)
        conn.commit()
        return (
            {
                "message": (
                    "コメントを報告しました。一定数の通報により非表示になりました。"
                    if hidden
                    else "コメントを報告しました。"
                ),
                "prompt_id": prompt_id,
                "comment_count": comment_count,
                "hidden": hidden,
                "already_reported": False,
            },
            201,
        )
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


@prompt_share_api_bp.get(
    "/prompts/{prompt_id}/comments",
    name="prompt_share_api.get_prompt_comments",
)
async def get_prompt_comments(prompt_id: int, request: Request):
    session = getattr(request, "session", {}) or {}
    actor_user_id = session.get("user_id")
    actor_is_admin = bool(session.get("is_admin"))
    try:
        response_payload, status_code = await run_blocking(
            _fetch_prompt_comments,
            prompt_id,
            actor_user_id,
            actor_is_admin,
        )
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to load prompt comments.",
        )


@prompt_share_api_bp.post(
    "/prompts/{prompt_id}/comments",
    name="prompt_share_api.create_prompt_comment",
)
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

    request_payload, validation_error = validate_payload_model(
        data,
        PromptCommentCreateRequest,
        error_message="コメント内容を入力してください。",
    )
    if validation_error is not None:
        return validation_error
    if _contains_too_many_links(request_payload.content):
        return jsonify({"error": "URLを含むコメントは3件までにしてください。"}, status_code=400)

    try:
        response_payload, status_code = await run_blocking(
            _add_prompt_comment_for_user,
            user_id,
            prompt_id,
            request_payload.content,
            actor_is_admin,
        )
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to create prompt comment.",
        )


@prompt_share_api_bp.delete(
    "/comments/{comment_id}",
    name="prompt_share_api.delete_prompt_comment",
)
async def delete_prompt_comment(comment_id: int, request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)

    actor_user_id = int(request.session["user_id"])
    actor_is_admin = bool(request.session.get("is_admin"))
    try:
        response_payload, status_code = await run_blocking(
            _delete_prompt_comment_for_actor,
            actor_user_id,
            comment_id,
            actor_is_admin,
        )
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to delete prompt comment.",
        )


@prompt_share_api_bp.post(
    "/comments/{comment_id}/report",
    name="prompt_share_api.report_prompt_comment",
)
async def report_prompt_comment(comment_id: int, request: Request):
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)

    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    request_payload, validation_error = validate_payload_model(
        data,
        PromptCommentReportRequest,
        error_message="報告理由を指定してください。",
    )
    if validation_error is not None:
        return validation_error

    try:
        response_payload, status_code = await run_blocking(
            _report_prompt_comment_for_user,
            int(request.session["user_id"]),
            comment_id,
            request_payload.reason,
            request_payload.details,
        )
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to report prompt comment.",
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
