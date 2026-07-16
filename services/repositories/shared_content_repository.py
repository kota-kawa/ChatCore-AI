from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from services.db import get_db_connection


# 一覧では全文をDBから運ばず、serviceで短いsnippetへ整形するための十分な先頭部分だけを取得する。
# List queries fetch only a bounded prefix; the service turns it into a short snippet.
SNIPPET_SOURCE_MAX_LENGTH = 1000


class SharedContentRepository:
    """公開プロンプト/SKILLの読み取り専用永続化境界。"""

    def __init__(
        self,
        *,
        connection_getter: Callable[[], Any] = get_db_connection,
    ) -> None:
        self._connection_getter = connection_getter

    def list_public_content(
        self,
        *,
        limit: int,
        cursor: tuple[datetime, int] | None = None,
        query: str | None = None,
        category: str | None = None,
        content_format: str | None = None,
        media_type: str | None = None,
        matching_category_keys: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """公開・未削除の投稿を(created_at, id)の安定順で1ページ取得する。"""

        conditions = ["p.is_public = TRUE", "p.deleted_at IS NULL"]
        filter_params: list[Any] = []

        if category is not None:
            conditions.append("p.category = %s")
            filter_params.append(category)
        if content_format is not None:
            conditions.append("p.content_format = %s")
            filter_params.append(content_format)
        if media_type is not None:
            conditions.append("p.media_type = %s")
            filter_params.append(media_type)
        if query:
            escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like_query = f"%{escaped_query}%"
            conditions.append(
                """(
                    p.title ILIKE %s ESCAPE '\\'
                    OR p.content ILIKE %s ESCAPE '\\'
                    OR p.category ILIKE %s ESCAPE '\\'
                    OR p.category = ANY(%s::text[])
                    OR p.author ILIKE %s ESCAPE '\\'
                    OR u.username ILIKE %s ESCAPE '\\'
                    OR (
                        p.content_format = 'skill'
                        AND COALESCE(p.attributes->>'skill_markdown', '') ILIKE %s ESCAPE '\\'
                    )
                )"""
            )
            filter_params.extend(
                [
                    like_query,
                    like_query,
                    like_query,
                    matching_category_keys or [],
                    like_query,
                    like_query,
                    like_query,
                ]
            )
        if cursor is not None:
            conditions.append("(p.created_at, p.id) < (%s, %s)")
            filter_params.extend(cursor)

        # 1件余分に取得し、全件COUNTなしで次ページの有無を判定する。
        # Fetch one extra row to determine has_next without an exact COUNT.
        params = [SNIPPET_SOURCE_MAX_LENGTH, *filter_params, limit + 1]
        where_sql = "\n                  AND ".join(conditions)
        sql = f"""
            SELECT
                p.id,
                p.title,
                p.category,
                COALESCE(u.username, p.author, 'ユーザー') AS author,
                p.content_format,
                p.media_type,
                LEFT(
                    CASE
                        WHEN p.content_format = 'skill'
                            THEN COALESCE(p.attributes->>'skill_markdown', '')
                        ELSE p.content
                    END,
                    %s
                ) AS snippet_source,
                p.created_at
            FROM prompts AS p
            LEFT JOIN users AS u
              ON u.id = p.user_id
            WHERE {where_sql}
            ORDER BY p.created_at DESC, p.id DESC
            LIMIT %s
        """

        conn = None
        db_cursor = None
        try:
            conn = self._connection_getter()
            db_cursor = conn.cursor(dictionary=True)
            db_cursor.execute(sql, tuple(params))
            rows = [dict(row) for row in db_cursor.fetchall()]
            has_next = len(rows) > limit
            return rows[:limit], has_next
        finally:
            if db_cursor is not None:
                db_cursor.close()
            if conn is not None:
                conn.close()

    def get_public_content(self, prompt_id: int) -> dict[str, Any] | None:
        """IDに一致する公開・未削除の投稿全文を取得する。"""

        conn = None
        db_cursor = None
        try:
            conn = self._connection_getter()
            db_cursor = conn.cursor(dictionary=True)
            db_cursor.execute(
                """
                SELECT
                    p.id,
                    p.title,
                    p.category,
                    p.content,
                    COALESCE(u.username, p.author, 'ユーザー') AS author,
                    p.content_format,
                    p.media_type,
                    p.attributes,
                    p.attachments,
                    p.input_examples,
                    p.output_examples,
                    p.ai_model,
                    p.created_at,
                    p.updated_at
                FROM prompts AS p
                LEFT JOIN users AS u
                  ON u.id = p.user_id
                WHERE p.id = %s
                  AND p.is_public = TRUE
                  AND p.deleted_at IS NULL
                LIMIT 1
                """,
                (prompt_id,),
            )
            row = db_cursor.fetchone()
            return dict(row) if row else None
        finally:
            if db_cursor is not None:
                db_cursor.close()
            if conn is not None:
                conn.close()
