from __future__ import annotations

from decimal import Decimal
import sys
from typing import Any

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.datetime_serialization import serialize_datetime_iso
from services.db import get_db_connection as default_get_db_connection
from .constants import (
    COLLECTION_NOT_FOUND_ERROR,
    MEMO_NOT_FOUND_ERROR,
)
from .helpers import date_end, date_start, ensure_title, resolve_sort_order
from .serializers import serialize_memo_detail, serialize_memo_summary


def _get_db_connection():
    """
    メモモジュールから動的にDB接続取得関数を解決するヘルパー（循環参照防止）
    Helper to dynamically retrieve the DB connection function to avoid circular imports.

    Returns:
        Connection: データベース接続オブジェクト / The database connection object.
    """
    memo_module = sys.modules.get("blueprints.memo")
    if memo_module is not None:
        return getattr(memo_module, "get_db_connection", default_get_db_connection)()
    return default_get_db_connection()


def _serialize_vector(embedding: list[float]) -> str:
    """Serialize an embedding as PostgreSQL pgvector input."""
    values = [float(value) for value in embedding]
    if not values:
        raise ValueError("Embedding must not be empty.")
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"


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
    """
    条件フィルターおよびソート設定に基づき、メモの概要リストを取得する関数
    Retrieve a list of memo summaries based on filters and sorting criteria.

    Args:
        user_id (int): ユーザーID / User ID.
        limit (int): 取得上限件数 / Pagination limit.
        offset (int): 取得オフセット / Pagination offset.
        query (str): テキスト検索クエリ / Text search keyword.
        date_from (str): 開始日付 / Start date filter.
        date_to (str): 終了日付 / End date filter.
        sort (str): ソート方法 / Sorting algorithm key.
        include_archived (bool): アーカイブ済みメモを含めるか / Whether to include archived memos.
        only_archived (bool): アーカイブ済みメモのみ対象とするか / Whether to load only archived memos.
        pinned_first (bool): ピン留めメモを優先的に先頭に配置するか / Whether to display pinned memos first.
        collection_id (int | None): コレクションIDによる絞り込み / Optional collection ID to filter by.
        semantic_query_embedding (list[float] | None): セマンティック検索用のクエリ埋め込みベクトル / Optional query embedding vector for semantic search.

    Returns:
        dict[str, Any]: 総件数とメモ概要のリスト / Dictionary containing total count and lists of serialized memo summaries.
    """
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # 基本的なWHERE句を設定（ユーザーID一致）
        # Set basic WHERE clause (user ID match).
        where_clauses = ["me.user_id = %s"]
        filter_params: list[Any] = [user_id]

        # アーカイブ状態によるフィルタリング
        # Filter based on archived state.
        if only_archived:
            where_clauses.append("me.archived_at IS NOT NULL")
        elif not include_archived:
            where_clauses.append("me.archived_at IS NULL")

        # キーワード検索（セマンティック検索でない場合）
        # Text-based keyword search (when not using semantic search).
        normalized_query = query.strip()
        if normalized_query and not semantic_query_embedding:
            query_like = f"%{normalized_query}%"
            where_clauses.append(
                "(me.title ILIKE %s OR me.ai_response ILIKE %s)"
            )
            filter_params.extend([query_like, query_like])

        # 作成日時による範囲指定フィルタリング
        # Filter by created_at datetime range.
        parsed_date_from = date_start(date_from)
        if parsed_date_from is not None:
            filter_params.append(parsed_date_from)
            where_clauses.append("me.created_at >= %s")

        parsed_date_to = date_end(date_to)
        if parsed_date_to is not None:
            filter_params.append(parsed_date_to)
            where_clauses.append("me.created_at <= %s")

        # コレクションIDによるフィルタリング
        # Filter by collection ID.
        if collection_id is not None:
            filter_params.append(collection_id)
            where_clauses.append("me.collection_id = %s")

        where_sql = " AND ".join(where_clauses)

        # セマンティック検索は pgvector の距離演算と HNSW インデックスで DB 側に委譲する。
        # Perform semantic ranking in PostgreSQL with pgvector rather than transferring and sorting candidates in Python.
        if semantic_query_embedding is not None:
            where_clauses_sem = list(where_clauses)
            where_clauses_sem.append("me.embedding_vector IS NOT NULL")
            where_sem_sql = " AND ".join(where_clauses_sem)
            semantic_vector = _serialize_vector(semantic_query_embedding)

            # 検索可能な埋め込みを持つメモだけを件数に含める。
            # Count only entries eligible for semantic ranking.
            count_sql = f"SELECT COUNT(*) AS total_count FROM memo_entries me WHERE {where_sem_sql}"
            cursor.execute(count_sql, tuple(filter_params))
            count_row = cursor.fetchone() or {}
            total_count = int(count_row.get("total_count") or 0)

            # HNSW 索引で近傍を取得し、ページ分だけ DB から返す。
            # Retrieve only the requested nearest neighbours through the HNSW index.
            sem_sql = f"""
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
                WHERE {where_sem_sql}
                ORDER BY me.embedding_vector <=> %s::vector
                LIMIT %s
                OFFSET %s
            """
            cursor.execute(sem_sql, tuple([*filter_params, semantic_vector, limit, offset]))
            rows = list(cursor.fetchall())
            return {
                "total": total_count,
                "memos": [serialize_memo_summary(row) for row in rows],
            }

        # 通常ソート条件の組み立て（ピン留め優先対応など）
        # Construct SQL ORDER BY clauses for normal queries.
        order_by_parts: list[str] = []
        if pinned_first:
            order_by_parts.append("CASE WHEN me.pinned_at IS NULL THEN 1 ELSE 0 END ASC")
            if sort != "manual":
                order_by_parts.append("me.pinned_at DESC")
        order_by_parts.append(resolve_sort_order(sort))
        order_sql = ", ".join(order_by_parts)

        # 通常クエリでの総件数取得
        # Fetch total count for standard query.
        count_sql = f"SELECT COUNT(*) AS total_count FROM memo_entries me WHERE {where_sql}"
        cursor.execute(count_sql, tuple(filter_params))
        count_row = cursor.fetchone() or {}
        total_count = int(count_row.get("total_count") or 0)

        # 通常クエリでのメモ一覧取得
        # Retrieve paginated memo records.
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
    """
    指定されたメモの詳細情報を取得する関数
    Retrieve the detailed data for a specific memo entry.

    Args:
        user_id (int): ユーザーID / User ID.
        memo_id (int): メモID / Memo ID.

    Returns:
        dict[str, Any]: シリアライズされたメモ詳細データ / Serialized memo detailed dictionary.
    """
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
        # メモが見つからない場合は例外を送出
        # Raise an exception if the memo is not found.
        if not row:
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
        return serialize_memo_detail(row)
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def validate_collection_owner(cursor: Any, user_id: int, collection_id: int) -> bool:
    """
    指定されたコレクションがユーザー所有のものか検証する関数
    Validate whether the specified collection belongs to the user.

    Args:
        cursor (Any): データベースカーソル / The database cursor.
        user_id (int): ユーザーID / User ID.
        collection_id (int): コレクションID / Collection ID.

    Returns:
        bool: 所有している場合はTrue、それ以外はFalse / True if owned by user, False otherwise.
    """
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
    """
    メモをDBに新規挿入・保存する関数
    Insert and save a new memo entry in the database.

    Args:
        user_id (int): ユーザーID / User ID.
        ai_response (str): AIの回答本文 / The AI response text content.
        resolved_title (str): 決定されたタイトル / The memo title.
        collection_id (int | None): 所属させるコレクションのID / Collection ID or None.
        background_color (str | None): 背景色の指定 / The CSS background color.

    Returns:
        int | None: 挿入されたメモのID / The inserted memo ID, or None on failure.
    """
    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
        cursor = connection.cursor()

        # コレクションIDが渡された場合、所有権を事前に検証
        # Verify collection ownership if provided.
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

        # メモをデータベースにインサート（sort_orderは最大値に+1して末尾に追加）
        # Insert the memo (assigning next sort order sequence number).
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
    """
    メモの属性情報（タイトル、コンテンツ、コレクション等）を更新する関数
    Update metadata or content attributes of a memo entry.

    Args:
        user_id (int): ユーザーID / User ID.
        memo_id (int): 対象メモID / Target memo ID.
        title (str | None): 新しいタイトル / New title or None to keep existing.
        ai_response (str | None): 新しい回答コンテンツ / New content or None to keep existing.
        collection_id (int | None): コレクションID / Collection ID or None to keep existing.
        clear_collection (bool): コレクション紐付けを解除するかどうか / Whether to clear the collection association.
        background_color (str | None): 新しい背景色 / New background color or None.
        clear_background_color (bool): 背景色指定をクリアするかどうか / Whether to clear the background color.

    Returns:
        dict[str, Any]: 更新後のメモ詳細 / The updated memo detail dictionary.
    """
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

        # メモ本文の更新判定とバリデーション
        # Determine updated content value and validate.
        resolved_ai_response = existing.get("ai_response") or ""
        if ai_response is not None:
            resolved_ai_response = ai_response
        if not str(resolved_ai_response).strip():
            raise ApiServiceError("AIの回答を入力してください。", 400, status="fail")

        # タイトルの更新判定
        # Resolve title update.
        resolved_title = existing.get("title") or ""
        if title is not None:
            resolved_title = ensure_title(str(resolved_ai_response), title)

        # コレクション設定の更新判定（クリア指定または新規ID指定）
        # Resolve collection relationship update (clear or set new ID).
        resolved_collection: int | None = existing.get("collection_id")
        if clear_collection:
            resolved_collection = None
        elif collection_id is not None:
            if validate_collection_owner(cursor, user_id, collection_id):
                resolved_collection = collection_id

        # 背景色の更新判定（クリア指定または新規カラー指定）
        # Resolve background color update (clear or set new color).
        if clear_background_color:
            resolved_background_color = None
        else:
            resolved_background_color = (
                background_color
                if background_color is not None
                else existing.get("background_color")
            )

        # データベースに更新を書き込み
        # Write updates to the database.
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
    """
    メモのアーカイブ状態を設定する関数
    Set the archived state (archived_at timestamp) of a memo.

    Args:
        user_id (int): ユーザーID / User ID.
        memo_id (int): 対象メモID / Target memo ID.
        enabled (bool): アーカイブに設定するかどうか / True to archive, False to unarchive.

    Returns:
        dict[str, Any]: 更新後のメモ詳細 / The updated memo detail dictionary.
    """
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
    """
    メモのピン留め状態を設定する関数
    Set the pinned state (pinned_at timestamp) and adjust manual sort order.

    Args:
        user_id (int): ユーザーID / User ID.
        memo_id (int): 対象メモID / Target memo ID.
        enabled (bool): ピン留めを設定するかどうか / True to pin, False to unpin.

    Returns:
        dict[str, Any]: 更新後のメモ詳細 / The updated memo detail dictionary.
    """
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
    """
    値を安全にDecimal型に変換する内部ヘルパー
    Internal helper to safely cast a value to Decimal.

    Args:
        value (Any): 変換対象の値 / The value to convert.

    Returns:
        Decimal: 変換されたDecimalオブジェクト / Decimal representation of the value.
    """
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
    """
    メモの表示順（並び順）をドラッグ＆ドロップ先の近隣要素情報から再計算して更新する関数
    Update manual sorting order based on target neighbors.

    Args:
        user_id (int): ユーザーID / User ID.
        memo_id (int): 移動対象のメモID / Target memo ID to move.
        before_id (int | None): 移動先で直前に位置するメモのID / The memo ID positioned before this after move.
        after_id (int | None): 移動先で直後に位置するメモのID / The memo ID positioned after this after move.

    Returns:
        dict[str, Any]: 更新されたメモ詳細情報 / The reordered memo details.
    """
    # 移動先と自身のIDが重複している場合はエラー
    # Error out if neighbors match the moving memo ID.
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
        # 対象メモおよび近隣メモの現在の並び順と状態を取得
        # Retrieve current sort orders and states of target memos.
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

        # 近隣メモのソートオーダーを解決し、状態不整合をバリデーションする内部ヘルパー
        # Resolve neighbor sort order and validate consistent states (pinned/archived).
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

        # 順序の決定（前後要素の中間値、または増減値）
        # Calculate new order position (midpoint between neighbors, or increments).
        if before_order is not None and after_order is not None:
            new_order = (before_order + after_order) / Decimal("2")
        elif before_order is not None:
            new_order = before_order - Decimal("1")
        elif after_order is not None:
            new_order = after_order + Decimal("1")
        else:
            # 近隣情報が全く無い場合は同一セクション内の最大値に+1を設定
            # If no neighbor info, default to the maximum order + 1 in that group.
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

        # 並び順を更新
        # Update manual sequence value.
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
    """
    メモをDBから完全に削除する関数
    Permanently delete a memo entry from the database.

    Args:
        user_id (int): ユーザーID / User ID.
        memo_id (int): メモID / The memo ID.

    Returns:
        None
    """
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
    """
    複数メモに対して一括操作（アーカイブ、削除、ピン留め、コレクション割当等）を行う関数
    Perform bulk action (delete, archive, pin, unpin, assign collection) on multiple memos.

    Args:
        user_id (int): ユーザーID / User ID.
        action (str): アクション種別 / Action type.
        memo_ids (list[int]): 対象メモIDの一覧 / List of memo IDs.
        collection_id (int | None): コレクションID（コレクション設定時のみ使用） / Collection ID.

    Returns:
        dict[str, Any]: 影響を受けた行数を含む辞書 / Affected row counts.
    """
    if not memo_ids:
        return {"affected": 0}

    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
        cursor = connection.cursor()

        placeholders = ",".join(["%s"] * len(memo_ids))
        # 指定されたIDのうち、ユーザーが所有するもののみ抽出
        # Filter target memo IDs to only those owned by the user.
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

        # 各アクションに対応するSQLの実行
        # Execute the specified bulk action.
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
            # コレクションの所有者検証
            # Verify collection owner.
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
    """
    所有するコレクションの一覧および各所属メモ数を取得する関数
    Fetch all memo collections of a user including active memo count in each.

    Args:
        user_id (int): ユーザーID / User ID.

    Returns:
        list[dict[str, Any]]: 各コレクションの情報のリスト / List of serialized collections.
    """
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
    """
    コレクションを新規作成してDBに挿入する関数
    Create and insert a new memo collection.

    Args:
        user_id (int): ユーザーID / User ID.
        name (str): コレクション名 / Name of the collection.
        color (str): コレクションの表示色 (CSS形式等) / Color hex or string representation.

    Returns:
        dict[str, Any]: 作成されたコレクション情報 / The created collection dictionary.
    """
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
    """
    コレクションの名前または色情報を更新する関数
    Update collection attributes (name and/or color).

    Args:
        user_id (int): ユーザーID / User ID.
        collection_id (int): コレクションID / Target collection ID.
        name (str | None): 新しい名前 / Optional new name.
        color (str | None): 新しい色 / Optional new color.

    Returns:
        dict[str, Any]: 更新されたコレクション情報 / The updated collection dictionary.
    """
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

        # 所属する有効なメモの総数をカウント
        # Count non-archived memos currently in this collection.
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
    """
    コレクションを削除する関数
    Delete a memo collection.

    Args:
        user_id (int): ユーザーID / User ID.
        collection_id (int): コレクションID / Target collection ID.

    Returns:
        None
    """
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
