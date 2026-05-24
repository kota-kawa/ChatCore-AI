from __future__ import annotations

from decimal import Decimal
import sys
from typing import Any

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.datetime_serialization import serialize_datetime_iso
from services.db import get_db_connection as default_get_db_connection
from services.memo_ai import rank_memos_by_semantic_similarity

from .constants import (
    COLLECTION_NOT_FOUND_ERROR,
    MEMO_NOT_FOUND_ERROR,
    SEMANTIC_SEARCH_MAX_MEMOS,
)
from .helpers import date_end, date_start, ensure_title, resolve_sort_order
from .serializers import serialize_memo_detail, serialize_memo_summary


def _get_db_connection():
    memo_module = sys.modules.get("blueprints.memo")
    if memo_module is not None:
        return getattr(memo_module, "get_db_connection", default_get_db_connection)()
    return default_get_db_connection()


def fetch_memo_summaries(
    user_id: int,
    *,
    limit: int,
    offset: int,
    query: str,
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
        connection = _get_db_connection()
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
                "(me.title ILIKE %s OR me.ai_response ILIKE %s)"
            )
            filter_params.extend([query_like, query_like])

        parsed_date_from = date_start(date_from)
        if parsed_date_from is not None:
            filter_params.append(parsed_date_from)
            where_clauses.append("me.created_at >= %s")

        parsed_date_to = date_end(date_to)
        if parsed_date_to is not None:
            filter_params.append(parsed_date_to)
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
                    me.id, me.title, me.created_at, me.updated_at,
                    me.archived_at, me.pinned_at, me.embedding,
                    LEFT(COALESCE(me.ai_response, ''), 400) AS preview_response,
                    me.collection_id,
                    me.background_color,
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
                "memos": [serialize_memo_summary(r) for r in paginated],
            }

        order_by_parts: list[str] = []
        if pinned_first:
            order_by_parts.append("CASE WHEN me.pinned_at IS NULL THEN 1 ELSE 0 END ASC")
            if sort != "manual":
                order_by_parts.append("me.pinned_at DESC")
        order_by_parts.append(resolve_sort_order(sort))
        order_sql = ", ".join(order_by_parts)

        count_sql = f"SELECT COUNT(*) AS total_count FROM memo_entries me WHERE {where_sql}"
        cursor.execute(count_sql, tuple(filter_params))
        count_row = cursor.fetchone() or {}
        total_count = int(count_row.get("total_count") or 0)

        list_sql = f"""
            SELECT
                me.id, me.title, me.created_at, me.updated_at,
                me.archived_at, me.pinned_at,
                LEFT(COALESCE(me.ai_response, ''), 400) AS preview_response,
                me.collection_id,
                me.background_color,
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
            "memos": [serialize_memo_summary(row) for row in rows],
        }
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def fetch_memo_detail(user_id: int, memo_id: int) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                me.id, me.title, me.ai_response,
                me.created_at, me.updated_at, me.archived_at, me.pinned_at,
                me.collection_id,
                me.background_color,
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
        return serialize_memo_detail(row)
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def validate_collection_owner(cursor: Any, user_id: int, collection_id: int) -> bool:
    cursor.execute(
        "SELECT 1 FROM memo_collections WHERE id = %s AND user_id = %s",
        (collection_id, user_id),
    )
    return cursor.fetchone() is not None


def insert_memo(
    user_id: int,
    ai_response: str,
    resolved_title: str,
    collection_id: int | None,
    background_color: str | None = None,
) -> int | None:
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
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
            INSERT INTO memo_entries (
                user_id, ai_response, title, collection_id,
                background_color, sort_order
            )
            VALUES (
                %s, %s, %s, %s, %s,
                COALESCE((SELECT MAX(sort_order) FROM memo_entries WHERE user_id = %s), 0) + 1
            )
            RETURNING id
            """,
            (
                user_id,
                ai_response,
                resolved_title,
                validated_collection_id,
                background_color,
                user_id,
            ),
        )
        connection.commit()
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def update_memo(
    user_id: int,
    memo_id: int,
    *,
    title: str | None,
    ai_response: str | None,
    collection_id: int | None,
    clear_collection: bool,
    background_color: str | None = None,
    clear_background_color: bool = False,
) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT title, ai_response, collection_id, background_color
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
            resolved_title = ensure_title(str(resolved_ai_response), title)

        resolved_collection: int | None = existing.get("collection_id")
        if clear_collection:
            resolved_collection = None
        elif collection_id is not None:
            if validate_collection_owner(cursor, user_id, collection_id):
                resolved_collection = collection_id

        if clear_background_color:
            resolved_background_color = None
        else:
            resolved_background_color = (
                background_color
                if background_color is not None
                else existing.get("background_color")
            )
        cursor.execute(
            """
            UPDATE memo_entries
            SET title = %s, ai_response = %s,
                collection_id = %s,
                background_color = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s
            """,
            (
                resolved_title,
                resolved_ai_response,
                resolved_collection,
                resolved_background_color,
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

    return fetch_memo_detail(user_id, memo_id)


def set_memo_archive_state(user_id: int, memo_id: int, enabled: bool) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
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

    return fetch_memo_detail(user_id, memo_id)


def set_memo_pin_state(user_id: int, memo_id: int, enabled: bool) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE memo_entries
            SET pinned_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END,
                sort_order = CASE
                    WHEN %s THEN COALESCE((
                        SELECT MAX(sort_order)
                        FROM memo_entries
                        WHERE user_id = %s
                          AND archived_at IS NULL
                          AND pinned_at IS NOT NULL
                    ), 0) + 1
                    ELSE sort_order
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s
            RETURNING id
            """,
            (enabled, enabled, user_id, memo_id, user_id),
        )
        if not cursor.fetchone():
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
        connection.commit()
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return fetch_memo_detail(user_id, memo_id)


def _decimal_order(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


def reorder_memo(
    user_id: int,
    memo_id: int,
    *,
    before_id: int | None,
    after_id: int | None,
) -> dict[str, Any]:
    if before_id == memo_id or after_id == memo_id:
        raise ApiServiceError("並べ替え位置が不正です。", 400, status="fail")

    ordered_ids = [memo_id]
    for candidate in (before_id, after_id):
        if candidate is not None and candidate not in ordered_ids:
            ordered_ids.append(candidate)

    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
        cursor = connection.cursor(dictionary=True)

        placeholders = ",".join(["%s"] * len(ordered_ids))
        cursor.execute(
            f"""
            SELECT
                id,
                COALESCE(sort_order, EXTRACT(EPOCH FROM created_at)::numeric) AS sort_order,
                pinned_at,
                archived_at
            FROM memo_entries
            WHERE user_id = %s AND id IN ({placeholders})
            """,
            tuple([user_id, *ordered_ids]),
        )
        rows = {int(row["id"]): row for row in cursor.fetchall()}
        dragged = rows.get(memo_id)
        if dragged is None:
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)

        dragged_is_pinned = dragged.get("pinned_at") is not None
        dragged_is_archived = dragged.get("archived_at") is not None

        def neighbor_order(neighbor_id: int | None) -> Decimal | None:
            if neighbor_id is None:
                return None
            neighbor = rows.get(neighbor_id)
            if neighbor is None:
                raise ApiServiceError("並べ替え先のメモが見つかりません。", 400, status="fail")
            if (
                (neighbor.get("pinned_at") is not None) != dragged_is_pinned
                or (neighbor.get("archived_at") is not None) != dragged_is_archived
            ):
                raise ApiServiceError("ピン留めまたはアーカイブ状態が異なるメモの間には移動できません。", 400, status="fail")
            return _decimal_order(neighbor.get("sort_order"))

        before_order = neighbor_order(before_id)
        after_order = neighbor_order(after_id)

        if before_order is not None and after_order is not None:
            new_order = (before_order + after_order) / Decimal("2")
        elif before_order is not None:
            new_order = before_order - Decimal("1")
        elif after_order is not None:
            new_order = after_order + Decimal("1")
        else:
            cursor.execute(
                """
                SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order
                FROM memo_entries
                WHERE user_id = %s
                  AND (pinned_at IS NOT NULL) = %s
                  AND (archived_at IS NOT NULL) = %s
                """,
                (user_id, dragged_is_pinned, dragged_is_archived),
            )
            next_row = cursor.fetchone() or {}
            new_order = _decimal_order(next_row.get("next_order"))

        cursor.execute(
            """
            UPDATE memo_entries
            SET sort_order = %s
            WHERE id = %s AND user_id = %s
            RETURNING id
            """,
            (new_order, memo_id, user_id),
        )
        if not cursor.fetchone():
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
        connection.commit()
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return fetch_memo_detail(user_id, memo_id)


def delete_memo(user_id: int, memo_id: int) -> None:
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
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


def bulk_action(
    user_id: int,
    action: str,
    memo_ids: list[int],
    *,
    collection_id: int | None,
) -> dict[str, Any]:
    if not memo_ids:
        return {"affected": 0}

    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
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
        affected = 0

        if action == "delete":
            cursor.execute(
                f"DELETE FROM memo_entries WHERE id IN ({owned_ph})",
                tuple(owned_ids),
            )
            affected = max(cursor.rowcount, 0)
        elif action == "archive":
            cursor.execute(
                f"UPDATE memo_entries SET archived_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id IN ({owned_ph})",
                tuple(owned_ids),
            )
            affected = max(cursor.rowcount, 0)
        elif action == "unarchive":
            cursor.execute(
                f"UPDATE memo_entries SET archived_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id IN ({owned_ph})",
                tuple(owned_ids),
            )
            affected = max(cursor.rowcount, 0)
        elif action == "pin":
            cursor.execute(
                f"UPDATE memo_entries SET pinned_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id IN ({owned_ph})",
                tuple(owned_ids),
            )
            affected = max(cursor.rowcount, 0)
        elif action == "unpin":
            cursor.execute(
                f"UPDATE memo_entries SET pinned_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id IN ({owned_ph})",
                tuple(owned_ids),
            )
            affected = max(cursor.rowcount, 0)
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
                affected = max(cursor.rowcount, 0)
        elif action == "clear_collection":
            cursor.execute(
                f"UPDATE memo_entries SET collection_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE id IN ({owned_ph})",
                tuple(owned_ids),
            )
            affected = max(cursor.rowcount, 0)

        connection.commit()
        return {"affected": affected}
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def fetch_collections(user_id: int) -> list[dict[str, Any]]:
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
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


def insert_collection(user_id: int, name: str, color: str) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
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


def update_collection(user_id: int, collection_id: int, name: str | None, color: str | None) -> dict[str, Any]:
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
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


def delete_collection(user_id: int, collection_id: int) -> None:
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
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
