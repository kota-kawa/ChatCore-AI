from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date, datetime, time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.async_utils import run_blocking
from services.background_executor import get_background_executor
from services.csrf import require_csrf
from services.datetime_serialization import serialize_datetime_iso
from services.db import Error, get_db_connection
from services.error_messages import (
    ERROR_LOGIN_REQUIRED,
    ERROR_MEMO_NOT_FOUND_FOR_SHARE,
    ERROR_TOKEN_REQUIRED,
)
from services.memo_ai import (
    build_memo_embedding_text,
    embeddings_available,
    generate_embedding,
    rank_memos_by_semantic_similarity,
    suggest_title_and_tags,
)
from services.memo_share import (
    create_or_get_shared_memo_token,
    get_memo_share_state,
    get_shared_memo_payload,
    revoke_shared_memo_token,
)
from services.request_models import (
    MemoBulkActionRequest,
    MemoCollectionCreateRequest,
    MemoCollectionUpdateRequest,
    MemoCreateRequest,
    MemoShareCreateRequest,
    MemoSuggestRequest,
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
COLLECTION_NOT_FOUND_ERROR = "コレクションが見つかりません。"
DEFAULT_MEMO_LIST_LIMIT = 20
MAX_MEMO_LIST_LIMIT = 100
DEFAULT_EXCERPT_LENGTH = 180
SEMANTIC_SEARCH_MAX_MEMOS = 500

memo_bp = APIRouter(prefix="/memo", dependencies=[Depends(require_csrf)])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_title(ai_response: str, provided_title: str) -> str:
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
        "collection_id": memo.get("collection_id"),
        "collection_name": memo.get("collection_name"),
        "collection_color": memo.get("collection_color"),
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
        "collection_id": memo.get("collection_id"),
        "collection_name": memo.get("collection_name"),
        "collection_color": memo.get("collection_color"),
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


# ---------------------------------------------------------------------------
# DB operations – memo list / detail
# ---------------------------------------------------------------------------

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
    collection_id: int | None,
    semantic_query_embedding: list[float] | None,
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
        if normalized_query and not semantic_query_embedding:
            query_like = f"%{normalized_query}%"
            where_clauses.append(
                "(me.title ILIKE %s OR me.tags ILIKE %s OR me.input_content ILIKE %s OR me.ai_response ILIKE %s)"
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

        if collection_id is not None:
            filter_params.append(collection_id)
            where_clauses.append("me.collection_id = %s")

        where_sql = " AND ".join(where_clauses)

        # For semantic search: fetch all matching memos (up to cap), rank in Python
        if semantic_query_embedding is not None:
            where_clauses_sem = list(where_clauses)
            where_clauses_sem.append("me.embedding IS NOT NULL")
            where_sem_sql = " AND ".join(where_clauses_sem)

            count_sql = f"SELECT COUNT(*) AS total_count FROM memo_entries me WHERE {where_sql}"
            cursor.execute(count_sql, tuple(filter_params))
            count_row = cursor.fetchone() or {}
            total_count = int(count_row.get("total_count") or 0)

            sem_sql = f"""
                SELECT
                    me.id, me.title, me.tags, me.created_at, me.updated_at,
                    me.archived_at, me.pinned_at, me.embedding,
                    LEFT(COALESCE(me.ai_response, ''), 400) AS preview_response,
                    me.collection_id,
                    mc.name AS collection_name,
                    mc.color AS collection_color,
                    sme.share_token, sme.expires_at, sme.revoked_at
                FROM memo_entries me
                LEFT JOIN memo_collections mc ON mc.id = me.collection_id
                LEFT JOIN shared_memo_entries sme ON sme.memo_entry_id = me.id
                WHERE {where_sem_sql}
                ORDER BY me.created_at DESC
                LIMIT %s
            """
            cursor.execute(sem_sql, tuple([*filter_params, SEMANTIC_SEARCH_MAX_MEMOS]))
            rows = list(cursor.fetchall())
            ranked = rank_memos_by_semantic_similarity(semantic_query_embedding, rows)
            paginated = ranked[offset : offset + limit]
            return {
                "total": total_count,
                "memos": [_serialize_memo_summary(r) for r in paginated],
            }

        order_by_parts: list[str] = []
        if pinned_first:
            order_by_parts.append("CASE WHEN me.pinned_at IS NULL THEN 1 ELSE 0 END ASC")
            order_by_parts.append("me.pinned_at DESC")
        order_by_parts.append(_resolve_sort_order(sort))
        order_sql = ", ".join(order_by_parts)

        count_sql = f"SELECT COUNT(*) AS total_count FROM memo_entries me WHERE {where_sql}"
        cursor.execute(count_sql, tuple(filter_params))
        count_row = cursor.fetchone() or {}
        total_count = int(count_row.get("total_count") or 0)

        list_sql = f"""
            SELECT
                me.id, me.title, me.tags, me.created_at, me.updated_at,
                me.archived_at, me.pinned_at,
                LEFT(COALESCE(me.ai_response, ''), 400) AS preview_response,
                me.collection_id,
                mc.name AS collection_name,
                mc.color AS collection_color,
                sme.share_token, sme.expires_at, sme.revoked_at
            FROM memo_entries me
            LEFT JOIN memo_collections mc ON mc.id = me.collection_id
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
                me.id, me.title, me.tags, me.input_content, me.ai_response,
                me.created_at, me.updated_at, me.archived_at, me.pinned_at,
                me.collection_id,
                mc.name AS collection_name,
                mc.color AS collection_color,
                sme.share_token, sme.expires_at, sme.revoked_at
            FROM memo_entries me
            LEFT JOIN memo_collections mc ON mc.id = me.collection_id
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


def _validate_collection_owner(cursor: Any, user_id: int, collection_id: int) -> bool:
    cursor.execute(
        "SELECT 1 FROM memo_collections WHERE id = %s AND user_id = %s",
        (collection_id, user_id),
    )
    return cursor.fetchone() is not None


def _insert_memo(
    user_id: int,
    input_content: str,
    ai_response: str,
    resolved_title: str,
    tags: str,
    collection_id: int | None,
) -> int | None:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        validated_collection_id: int | None = None
        if collection_id is not None:
            ccheck = connection.cursor(dictionary=True)
            try:
                ccheck.execute(
                    "SELECT 1 FROM memo_collections WHERE id = %s AND user_id = %s",
                    (collection_id, user_id),
                )
                if ccheck.fetchone():
                    validated_collection_id = collection_id
            finally:
                ccheck.close()

        cursor.execute(
            """
            INSERT INTO memo_entries (user_id, input_content, ai_response, title, tags, collection_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (user_id, input_content, ai_response, resolved_title, tags or None, validated_collection_id),
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
    collection_id: int | None,
    clear_collection: bool,
) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT title, tags, input_content, ai_response, collection_id FROM memo_entries WHERE id = %s AND user_id = %s LIMIT 1",
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
            resolved_tags = tags.strip() or None

        resolved_input = existing.get("input_content") or ""
        if input_content is not None:
            resolved_input = input_content

        resolved_collection: int | None = existing.get("collection_id")
        if clear_collection:
            resolved_collection = None
        elif collection_id is not None:
            if _validate_collection_owner(cursor, user_id, collection_id):
                resolved_collection = collection_id

        cursor.execute(
            """
            UPDATE memo_entries
            SET title = %s, tags = %s, input_content = %s, ai_response = %s,
                collection_id = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s
            """,
            (resolved_title, resolved_tags, resolved_input, resolved_ai_response,
             resolved_collection, memo_id, user_id),
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
            "DELETE FROM memo_entries WHERE id = %s AND user_id = %s RETURNING id",
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
    return {"status": "success", **share_state, "share_url": share_url}


# ---------------------------------------------------------------------------
# DB operations – embedding
# ---------------------------------------------------------------------------

def _store_embedding(memo_id: int, embedding: list[float]) -> None:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE memo_entries SET embedding = %s WHERE id = %s",
            (json.dumps(embedding), memo_id),
        )
        connection.commit()
    except Exception:
        logger.warning("Failed to store embedding for memo %s", memo_id, exc_info=True)
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def _schedule_embedding(memo_id: int, title: str, tags: str, ai_response: str) -> None:
    if not embeddings_available():
        return

    def _task() -> None:
        text = build_memo_embedding_text(title, tags, ai_response)
        embedding = generate_embedding(text)
        if embedding:
            _store_embedding(memo_id, embedding)

    try:
        get_background_executor().submit(_task)
    except Exception:
        logger.warning("Failed to schedule embedding task for memo %s", memo_id, exc_info=True)


# ---------------------------------------------------------------------------
# DB operations – bulk
# ---------------------------------------------------------------------------

def _bulk_action(
    user_id: int,
    action: str,
    memo_ids: list[int],
    *,
    tags: str | None,
    collection_id: int | None,
) -> dict[str, Any]:
    if not memo_ids:
        return {"affected": 0}

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        placeholders = ",".join(["%s"] * len(memo_ids))
        ownership_sql = f"""
            SELECT id FROM memo_entries
            WHERE user_id = %s AND id IN ({placeholders})
        """
        cursor.execute(ownership_sql, tuple([user_id, *memo_ids]))
        owned_ids = [row[0] for row in cursor.fetchall()]
        if not owned_ids:
            return {"affected": 0}

        owned_ph = ",".join(["%s"] * len(owned_ids))

        if action == "delete":
            cursor.execute(
                f"DELETE FROM memo_entries WHERE id IN ({owned_ph})",
                tuple(owned_ids),
            )
        elif action == "archive":
            cursor.execute(
                f"UPDATE memo_entries SET archived_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id IN ({owned_ph})",
                tuple(owned_ids),
            )
        elif action == "unarchive":
            cursor.execute(
                f"UPDATE memo_entries SET archived_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id IN ({owned_ph})",
                tuple(owned_ids),
            )
        elif action == "pin":
            cursor.execute(
                f"UPDATE memo_entries SET pinned_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id IN ({owned_ph})",
                tuple(owned_ids),
            )
        elif action == "unpin":
            cursor.execute(
                f"UPDATE memo_entries SET pinned_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id IN ({owned_ph})",
                tuple(owned_ids),
            )
        elif action == "add_tags" and tags is not None:
            normalized_tags = tags.strip()
            if normalized_tags:
                cursor.execute(
                    f"""
                    UPDATE memo_entries
                    SET tags = CASE
                        WHEN tags IS NULL OR tags = '' THEN %s
                        ELSE tags || ' ' || %s
                    END,
                    updated_at = CURRENT_TIMESTAMP
                    WHERE id IN ({owned_ph})
                    """,
                    tuple([normalized_tags, normalized_tags, *owned_ids]),
                )
        elif action == "set_collection" and collection_id is not None:
            cursor.execute(
                "SELECT 1 FROM memo_collections WHERE id = %s AND user_id = %s",
                (collection_id, user_id),
            )
            if cursor.fetchone():
                cursor.execute(
                    f"UPDATE memo_entries SET collection_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id IN ({owned_ph})",
                    tuple([collection_id, *owned_ids]),
                )
        elif action == "clear_collection":
            cursor.execute(
                f"UPDATE memo_entries SET collection_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE id IN ({owned_ph})",
                tuple(owned_ids),
            )

        connection.commit()
        return {"affected": len(owned_ids)}
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


# ---------------------------------------------------------------------------
# DB operations – export
# ---------------------------------------------------------------------------

def _fetch_memos_for_export(
    user_id: int,
    memo_ids: list[int] | None,
) -> list[dict[str, Any]]:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        if memo_ids:
            placeholders = ",".join(["%s"] * len(memo_ids))
            cursor.execute(
                f"""
                SELECT id, title, tags, input_content, ai_response, created_at, updated_at
                FROM memo_entries
                WHERE user_id = %s AND id IN ({placeholders})
                ORDER BY created_at DESC
                """,
                tuple([user_id, *memo_ids]),
            )
        else:
            cursor.execute(
                """
                SELECT id, title, tags, input_content, ai_response, created_at, updated_at
                FROM memo_entries
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 1000
                """,
                (user_id,),
            )
        return list(cursor.fetchall())
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def _build_markdown_export(memos: list[dict[str, Any]]) -> str:
    parts: list[str] = ["# メモエクスポート\n"]
    for memo in memos:
        title = memo.get("title") or "保存したメモ"
        tags = memo.get("tags") or ""
        created = serialize_datetime_iso(memo.get("created_at")) or ""
        input_c = _parse_memo_text(memo.get("input_content"))
        ai_resp = _parse_memo_text(memo.get("ai_response"))

        parts.append(f"## {title}\n")
        if tags:
            tag_list = " ".join(f"`{t}`" for t in tags.split())
            parts.append(f"**タグ:** {tag_list}\n")
        if created:
            parts.append(f"**作成日時:** {created}\n")
        if input_c:
            parts.append(f"\n### 入力内容\n\n{input_c}\n")
        if ai_resp:
            parts.append(f"\n### AIの回答\n\n{ai_resp}\n")
        parts.append("\n---\n\n")
    return "\n".join(parts)


def _build_json_export(memos: list[dict[str, Any]]) -> str:
    result = []
    for memo in memos:
        result.append({
            "id": memo.get("id"),
            "title": memo.get("title") or "保存したメモ",
            "tags": memo.get("tags") or "",
            "input_content": _parse_memo_text(memo.get("input_content")),
            "ai_response": _parse_memo_text(memo.get("ai_response")),
            "created_at": serialize_datetime_iso(memo.get("created_at")),
            "updated_at": serialize_datetime_iso(memo.get("updated_at")),
        })
    return json.dumps(result, ensure_ascii=False, indent=2)


def _build_csv_export(memos: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "title", "tags", "input_content", "ai_response", "created_at", "updated_at"])
    for memo in memos:
        writer.writerow([
            memo.get("id", ""),
            memo.get("title") or "保存したメモ",
            memo.get("tags") or "",
            _parse_memo_text(memo.get("input_content")),
            _parse_memo_text(memo.get("ai_response")),
            serialize_datetime_iso(memo.get("created_at")) or "",
            serialize_datetime_iso(memo.get("updated_at")) or "",
        ])
    return output.getvalue()


# ---------------------------------------------------------------------------
# DB operations – collections
# ---------------------------------------------------------------------------

def _fetch_collections(user_id: int) -> list[dict[str, Any]]:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT mc.id, mc.name, mc.color, mc.created_at, mc.updated_at,
                   COUNT(me.id) AS memo_count
            FROM memo_collections mc
            LEFT JOIN memo_entries me ON me.collection_id = mc.id AND me.archived_at IS NULL
            WHERE mc.user_id = %s
            GROUP BY mc.id, mc.name, mc.color, mc.created_at, mc.updated_at
            ORDER BY mc.created_at DESC
            """,
            (user_id,),
        )
        rows = list(cursor.fetchall())
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "color": r["color"],
                "memo_count": int(r["memo_count"] or 0),
                "created_at": serialize_datetime_iso(r["created_at"]),
                "updated_at": serialize_datetime_iso(r["updated_at"]),
            }
            for r in rows
        ]
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def _insert_collection(user_id: int, name: str, color: str) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            INSERT INTO memo_collections (user_id, name, color)
            VALUES (%s, %s, %s)
            RETURNING id, name, color, created_at, updated_at
            """,
            (user_id, name.strip(), color.strip()),
        )
        row = cursor.fetchone()
        connection.commit()
        if not row:
            raise RuntimeError("Insert did not return a row.")
        return {
            "id": row["id"],
            "name": row["name"],
            "color": row["color"],
            "memo_count": 0,
            "created_at": serialize_datetime_iso(row["created_at"]),
            "updated_at": serialize_datetime_iso(row["updated_at"]),
        }
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def _update_collection(user_id: int, collection_id: int, name: str | None, color: str | None) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT name, color FROM memo_collections WHERE id = %s AND user_id = %s",
            (collection_id, user_id),
        )
        existing = cursor.fetchone()
        if not existing:
            raise ResourceNotFoundError(COLLECTION_NOT_FOUND_ERROR)

        resolved_name = name.strip() if name is not None else existing["name"]
        resolved_color = color.strip() if color is not None else existing["color"]

        cursor.execute(
            """
            UPDATE memo_collections
            SET name = %s, color = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s
            RETURNING id, name, color, created_at, updated_at
            """,
            (resolved_name, resolved_color, collection_id, user_id),
        )
        row = cursor.fetchone()
        connection.commit()

        count_cur = connection.cursor(dictionary=True)
        try:
            count_cur.execute(
                "SELECT COUNT(*) AS c FROM memo_entries WHERE collection_id = %s AND archived_at IS NULL",
                (collection_id,),
            )
            count_row = count_cur.fetchone() or {}
        finally:
            count_cur.close()

        return {
            "id": row["id"],
            "name": row["name"],
            "color": row["color"],
            "memo_count": int(count_row.get("c") or 0),
            "created_at": serialize_datetime_iso(row["created_at"]),
            "updated_at": serialize_datetime_iso(row["updated_at"]),
        }
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def _delete_collection(user_id: int, collection_id: int) -> None:
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            "DELETE FROM memo_collections WHERE id = %s AND user_id = %s RETURNING id",
            (collection_id, user_id),
        )
        if not cursor.fetchone():
            raise ResourceNotFoundError(COLLECTION_NOT_FOUND_ERROR)
        connection.commit()
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

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
    collection_id: int | None = None,
):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    safe_limit = max(1, min(limit, MAX_MEMO_LIST_LIMIT))
    safe_offset = max(0, offset)

    semantic_embedding: list[float] | None = None
    if sort == "semantic" and q.strip() and embeddings_available():
        try:
            semantic_embedding = await run_blocking(generate_embedding, q.strip())
        except Exception:
            logger.warning("Failed to generate query embedding; falling back to text search.")

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
            payload.collection_id,
        )
        flash(request, "メモを保存しました。", "success")
        if memo_id:
            _schedule_embedding(memo_id, resolved_title, payload.tags, payload.ai_response)
        return jsonify({"status": "success", "memo_id": memo_id})
    except Error:
        return log_and_internal_server_error(logger, "Failed to create memo entry.", status="fail")


@memo_bp.post("/api/suggest", name="memo.api_suggest")
async def api_suggest_memo(request: Request):
    user_id = _user_id_from_session(request.session)
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
            suggest_title_and_tags,
            payload.input_content,
            payload.ai_response,
        )
        return jsonify({"status": "success", **result})
    except Exception:
        return log_and_internal_server_error(logger, "Memo suggestion failed.", status="fail")


@memo_bp.post("/api/bulk", name="memo.api_bulk")
async def api_bulk_memo(request: Request):
    user_id = _user_id_from_session(request.session)
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
            _bulk_action,
            user_id,
            payload.action,
            payload.memo_ids,
            tags=payload.tags,
            collection_id=payload.collection_id,
        )
        return jsonify({"status": "success", **result})
    except Error:
        return log_and_internal_server_error(logger, "Bulk memo action failed.", status="fail")


@memo_bp.get("/api/export", name="memo.api_export")
async def api_export_memos(
    request: Request,
    format: str = "markdown",
    ids: str = "",
):
    user_id = _user_id_from_session(request.session)
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
        memos = await run_blocking(_fetch_memos_for_export, user_id, memo_ids)

        if format == "json":
            content = _build_json_export(memos)
            media_type = "application/json"
            filename = "memos.json"
        elif format == "csv":
            content = _build_csv_export(memos)
            media_type = "text/csv; charset=utf-8"
            filename = "memos.csv"
        else:
            content = _build_markdown_export(memos)
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
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        collections = await run_blocking(_fetch_collections, user_id)
        return jsonify({"status": "success", "collections": collections})
    except Error:
        return log_and_internal_server_error(logger, "Failed to load collections.", status="fail")


@memo_bp.post("/api/collections", name="memo.api_collections_create")
async def api_create_collection(request: Request):
    user_id = _user_id_from_session(request.session)
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
            _insert_collection, user_id, payload.name, payload.color
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
    user_id = _user_id_from_session(request.session)
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
            _update_collection, user_id, collection_id, payload.name, payload.color
        )
        return jsonify({"status": "success", "collection": collection})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to update collection.", status="fail")


@memo_bp.delete("/api/collections/{collection_id:int}", name="memo.api_collections_delete")
async def api_delete_collection(request: Request, collection_id: int):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    try:
        await run_blocking(_delete_collection, user_id, collection_id)
        return jsonify({"status": "success"})
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to delete collection.", status="fail")


@memo_bp.post("/api/share", name="memo.api_share")
async def api_share_memo(request: Request):
    user_id = _user_id_from_session(request.session)
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
        return log_and_internal_server_error(logger, "Failed to create share link for memo entry.", status="fail")


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
        return log_and_internal_server_error(logger, "Failed to load shared memo payload.")


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
        data, MemoUpdateRequest, error_message="更新データが不正です。", status="fail",
    )
    if validation_error is not None:
        return validation_error

    if (
        payload.title is None
        and payload.tags is None
        and payload.input_content is None
        and payload.ai_response is None
        and payload.collection_id is None
        and not payload.clear_collection
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
            collection_id=payload.collection_id,
            clear_collection=payload.clear_collection,
        )
        if payload.ai_response is not None or payload.title is not None or payload.tags is not None:
            _schedule_embedding(
                memo_id,
                memo.get("title", ""),
                memo.get("tags", ""),
                memo.get("ai_response", ""),
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
        data, MemoToggleRequest, error_message="アーカイブ設定が不正です。", status="fail",
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
        data, MemoToggleRequest, error_message="ピン留め設定が不正です。", status="fail",
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
        return log_and_internal_server_error(logger, "Failed to load memo share status.", status="fail")


@memo_bp.post("/api/{memo_id:int}/share", name="memo.api_share_refresh")
async def api_memo_share_refresh(request: Request, memo_id: int):
    user_id = _user_id_from_session(request.session)
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
            create_or_get_shared_memo_token,
            memo_id,
            user_id,
            force_refresh=payload.force_refresh,
            expires_in_days=payload.expires_in_days,
        )
        return jsonify(_share_payload(share_state))
    except ApiServiceError as exc:
        return jsonify_service_error(exc, status="fail")
    except Error:
        return log_and_internal_server_error(logger, "Failed to refresh memo share status.", status="fail")


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
        return log_and_internal_server_error(logger, "Failed to revoke memo share link.", status="fail")


@memo_bp.api_route("", methods=["GET", "POST"], name="memo.create_memo")
async def create_memo(request: Request):
    status_code = 302 if request.method == "GET" else 303
    return redirect_to_frontend(request, status_code=status_code)
