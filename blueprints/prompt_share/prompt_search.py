# search_module.py
import logging

from fastapi import APIRouter, Request

from services.async_utils import run_blocking
from services.db import get_db_connection  # 既存の DB 接続関数を利用
# Reuse the shared DB connection helper.
from services.web import jsonify, log_and_internal_server_error

search_bp = APIRouter(prefix="/search")
logger = logging.getLogger(__name__)
SEARCH_DEFAULT_PAGE = 1
SEARCH_DEFAULT_PER_PAGE = 20
SEARCH_MAX_PER_PAGE = 100


def _parse_positive_int(raw_value: str | None, default: int) -> int:
    try:
        value = int(str(raw_value or "").strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _search_public_prompts(query, page, per_page):
    # 公開プロンプトを title/content/category/author で部分一致検索する
    # Search public prompts with partial matching across multiple columns.
    page = max(int(page), SEARCH_DEFAULT_PAGE)
    per_page = max(1, min(int(per_page), SEARCH_MAX_PER_PAGE))
    if not query:
        return {
            "prompts": [],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": 0,
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
            },
        }

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        offset = (page - 1) * per_page
        sql = """
            SELECT
              id,
              title,
              category,
              content,
              author,
              input_examples,
              output_examples,
              prompt_type,
              reference_image_url,
              created_at
            FROM prompts
            WHERE is_public = TRUE
              AND deleted_at IS NULL
              AND (
                title   LIKE %s OR
                content LIKE %s OR
                category LIKE %s OR
                author  LIKE %s
              )
            ORDER BY created_at DESC
            LIMIT %s
            OFFSET %s
        """
        count_sql = """
            SELECT COUNT(*) AS total
            FROM prompts
            WHERE is_public = TRUE
              AND deleted_at IS NULL
              AND (
                title   LIKE %s OR
                content LIKE %s OR
                category LIKE %s OR
                author  LIKE %s
              )
        """
        like_query = f"%{query}%"
        count_params = (like_query, like_query, like_query, like_query)
        cursor.execute(count_sql, count_params)
        count_row = cursor.fetchone() or {}
        total = int(count_row.get("total") or 0)

        cursor.execute(
            sql,
            (
                like_query,
                like_query,
                like_query,
                like_query,
                per_page,
                offset,
            ),
        )
        total_pages = (total + per_page - 1) // per_page if total > 0 else 0
        return {
            "prompts": cursor.fetchall(),
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > SEARCH_DEFAULT_PAGE and total > 0,
            },
        }
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@search_bp.get('/prompts', name="search.search_prompts")
async def search_prompts(request: Request):
    """
    クエリパラメータ q に基づいてプロンプトを検索するエンドポイント
    Search public prompts by query parameter `q`.
    """
    query = request.query_params.get('q', '').strip()
    page = _parse_positive_int(request.query_params.get("page"), SEARCH_DEFAULT_PAGE)
    per_page = _parse_positive_int(
        request.query_params.get("per_page"),
        SEARCH_DEFAULT_PER_PAGE,
    )
    try:
        payload = await run_blocking(_search_public_prompts, query, page, per_page)
        return jsonify({"status": "success", **payload})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to search public prompts.",
        )
