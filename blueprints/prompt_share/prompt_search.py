# search_module.py
import logging

from fastapi import APIRouter, Request

from services.async_utils import run_blocking
from services.db import get_db_connection  # 既存の DB 接続関数を利用
# Reuse the shared DB connection helper.
from services.web import jsonify, log_and_internal_server_error

search_bp = APIRouter(prefix="/search")
logger = logging.getLogger(__name__)


def _search_public_prompts(query):
    # 公開プロンプトを title/content/category/author で部分一致検索する
    # Search public prompts with partial matching across multiple columns.
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        if not query:
            return []
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
        """
        like_query = f"%{query}%"
        cursor.execute(sql, (like_query, like_query, like_query, like_query))
        return cursor.fetchall()
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
    try:
        prompts = await run_blocking(_search_public_prompts, query)
        return jsonify({'prompts': prompts})
    except Exception:
        return log_and_internal_server_error(
            logger,
            "Failed to search public prompts.",
        )
