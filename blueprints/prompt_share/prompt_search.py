import logging
from typing import Any

from fastapi import APIRouter, Request

from services.async_utils import run_blocking
from services.db import get_db_connection  # 既存の DB 接続関数を利用
# Reuse the shared DB connection helper.
from services.web import jsonify, log_and_internal_server_error

# 検索機能用ルーターの初期化
# Initialize APIRouter for prompt search operations.
search_bp = APIRouter(prefix="/search")
logger = logging.getLogger(__name__)

# デフォルトの検索開始ページ
# Default starting page for pagination.
SEARCH_DEFAULT_PAGE = 1

# 1ページあたりのデフォルト表示件数
# Default number of items per page.
SEARCH_DEFAULT_PER_PAGE = 20

# 1ページあたりの最大表示件数制限
# Upper limit of items allowed per page.
SEARCH_MAX_PER_PAGE = 100

# 検索可能なプロンプトタイプのセット
# Set of allowed prompt types for filtering.
SEARCH_PROMPT_TYPES = {"text", "image", "skill"}


# クエリパラメータを安全に正の整数値に変換するヘルパー関数
# Helper function to safely convert a query parameter to a positive integer.
def _parse_positive_int(raw_value: str | None, default: int) -> int:
    """
    クエリパラメータなどの文字列を安全に正の整数にキャストする。失敗した場合はデフォルト値を返す。
    Safely cast query parameter or raw string to a positive integer. Returns default value on failure.
    """
    try:
        # 文字列のトリム処理をしてから整数への変換を試みる
        # Try converting after trimming whitespace.
        value = int(str(raw_value or "").strip())
    except (TypeError, ValueError):
        # 変換不可、または例外発生時はデフォルト値を返却
        # Return default value if Type/Value errors occur.
        return default
    # 0以下の数値の場合はデフォルト値を返却、それ以外は変換後の値を返却
    # Return default if value is not positive; otherwise return parsed value.
    return value if value > 0 else default


# 検索結果レコードの各フィールドを標準化・整形するヘルパー関数
# Helper function to normalize and format database row fields for the API response.
def _normalize_search_prompt_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    DBから取得したプロンプトレコードの値をAPI用に整形・標準化する。
    Format and normalize a database record of a prompt for API response serialization.
    """
    # 辞書オブジェクトをコピー
    # Copy the dictionary object.
    prompt = dict(row)
    created_at = prompt.get("created_at")
    # datetime型の日付データをISOフォーマット文字列にシリアライズ
    # Serialize datetime object to ISO format string.
    if created_at is not None and hasattr(created_at, "isoformat"):
        prompt["created_at"] = created_at.isoformat()
    
    # プロンプトタイプを小文字正規化して許容値か確認
    # Normalize the prompt type to lowercase and verify check.
    normalized_prompt_type = str(prompt.get("prompt_type") or "").strip().lower()
    if normalized_prompt_type in {"image", "skill"}:
        prompt["prompt_type"] = normalized_prompt_type
    else:
        # デフォルトはtextタイプとする
        # Fall back to text type by default.
        prompt["prompt_type"] = "text"
        
    # URLやマークダウンなどのオプショナルなフィールドを設定
    # Set optional fields like URL and markdown contents.
    prompt["reference_image_url"] = prompt.get("reference_image_url") or None
    prompt["skill_markdown"] = prompt.get("skill_markdown") or ""
    prompt["skill_python_script"] = prompt.get("skill_python_script") or ""
    
    # 評価・チャット利用状態の真偽値キャストと、コメント数キャストを実行
    # Cast interaction flags to Boolean and cast comment count to integer.
    prompt["liked"] = bool(prompt.get("liked"))
    prompt["used_in_chat"] = bool(prompt.get("used_in_chat"))
    prompt["comment_count"] = int(prompt.get("comment_count") or 0)
    return prompt


# プロンプトタイプフィルターを検証し、許容される値のみに正規化する関数
# Validate and normalize the prompt type filter value.
def _normalize_prompt_type_filter(value):
    """
    指定されたプロンプトタイプが許可された検索セットに含まれるか検証し、正規化する。
    Check if the specified prompt type is in the allowed search set, and return normalized string or None.
    """
    # 大文字小文字や前後の空白を除去して正規化
    # Normalize case and strip spaces.
    normalized = str(value or "").strip().lower()
    # 許可されたセット(SEARCH_PROMPT_TYPES)に含まれる場合のみ値を返し、それ以外はNoneを返す
    # Return normalized value if in allowed types; otherwise return None.
    return normalized if normalized in SEARCH_PROMPT_TYPES else None


# 公開プロンプトの部分一致検索をデータベースクエリとして実行する関数
# Database lookup function to search public prompts by keywords and optional types.
def _search_public_prompts(query, page, per_page, user_id=None, prompt_type=None):
    """
    公開プロンプトをデータベースから部分一致で検索する。ページネーションとインタラクション状態（Like等）の取得も行う。
    Perform a database query to search public prompts using partial match. Handles pagination and user-specific interaction status.
    """
    # ページ数と1ページあたり表示件数を許容範囲に制限
    # Constrain page and per_page sizes to valid boundaries.
    page = max(int(page), SEARCH_DEFAULT_PAGE)
    per_page = max(1, min(int(per_page), SEARCH_MAX_PER_PAGE))
    
    # 検索クエリが無い場合は空の結果を返す
    # Return empty response immediately if query is empty.
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
        # DB接続を取得し、レコードを辞書形式で取得するカーソルを生成
        # Retrieve a DB connection and create a cursor with dictionary return type.
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # ページネーション用オフセット計算
        # Calculate pagination offset.
        offset = (page - 1) * per_page
        
        # プロンプトタイプ指定の検証と追加SQL文の組み立て
        # Validate and construct optional SQL segments for prompt type filter.
        prompt_type_filter = _normalize_prompt_type_filter(prompt_type)
        select_type_condition = "AND COALESCE(p.prompt_type, 'text') = %s" if prompt_type_filter else ""
        count_type_condition = "AND COALESCE(prompt_type, 'text') = %s" if prompt_type_filter else ""
        
        # 検索結果取得用SQL
        # SQL query to retrieve matching prompts.
        # ユーザーごとのLike/チャット利用有無とコメント数をJOIN等で取得する
        # Join other tables to query user-specific interaction state and comment counts.
        sql = f"""
            SELECT
              p.id,
              p.title,
              p.category,
              p.content,
              COALESCE(u.username, p.author, 'ユーザー') AS author,
              p.input_examples,
              p.output_examples,
              p.prompt_type,
              p.reference_image_url,
              p.skill_markdown,
              p.skill_python_script,
              p.created_at,
              COALESCE(pc.comment_count, 0) AS comment_count,
              CASE WHEN pl.id IS NOT NULL THEN TRUE ELSE FALSE END AS liked,
              CASE WHEN used_tasks.id IS NOT NULL THEN TRUE ELSE FALSE END AS used_in_chat
            FROM prompts AS p
            LEFT JOIN users AS u
              ON u.id = p.user_id
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
            LEFT JOIN task_with_examples AS used_tasks
              ON used_tasks.user_id = %s
             AND used_tasks.deleted_at IS NULL
             AND (
                  used_tasks.source_prompt_id = p.id
                  OR (
                       used_tasks.source_prompt_id IS NULL
                       AND used_tasks.name = p.title
                     )
                 )
            WHERE p.is_public = TRUE
              AND p.deleted_at IS NULL
              {select_type_condition}
              AND (
                p.title   LIKE %s OR
                p.content LIKE %s OR
                p.category LIKE %s OR
                COALESCE(u.username, p.author) LIKE %s
              )
            ORDER BY p.created_at DESC
            LIMIT %s
            OFFSET %s
        """
        
        # 総ヒット数取得用SQL
        # SQL query to get the total hit count.
        count_sql = f"""
            SELECT COUNT(*) AS total
            FROM prompts AS p
            LEFT JOIN users AS u
              ON u.id = p.user_id
            WHERE p.is_public = TRUE
              AND p.deleted_at IS NULL
              {count_type_condition}
              AND (
                p.title   LIKE %s OR
                p.content LIKE %s OR
                p.category LIKE %s OR
                COALESCE(u.username, p.author) LIKE %s
              )
        """
        # LIKE検索用のワイルドカード付きパターンを作成
        # Create a search pattern with wildcards for LIKE operator.
        like_query = f"%{query}%"
        count_params = []
        if prompt_type_filter:
            count_params.append(prompt_type_filter)
        count_params.extend([like_query, like_query, like_query, like_query])
        
        # 件数のカウント実行
        # Execute counting.
        cursor.execute(count_sql, tuple(count_params))
        count_row = cursor.fetchone() or {}
        total = int(count_row.get("total") or 0)

        # 検索パラメータの構築
        # Build query arguments list.
        search_params = [
            user_id,
            user_id,
        ]
        if prompt_type_filter:
            search_params.append(prompt_type_filter)
        search_params.extend([
            like_query,
            like_query,
            like_query,
            like_query,
            per_page,
            offset,
        ])
        
        # 検索結果レコードの取得実行
        # Execute query retrieval.
        cursor.execute(
            sql,
            tuple(search_params),
        )
        # 総ページ数を算出
        # Calculate total pages.
        total_pages = (total + per_page - 1) // per_page if total > 0 else 0
        return {
            "prompts": [_normalize_search_prompt_row(dict(row)) for row in cursor.fetchall()],
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
        # カーソルとデータベース接続を確実に解放
        # Ensure cursor and database connection are properly closed.
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# クエリパラメータに基づいてプロンプトを検索しJSONで返却するエンドポイント
# Endpoint to search public prompts by query parameter `q` and return JSON.
@search_bp.get('/prompts', name="search.search_prompts")
async def search_prompts(request: Request):
    """
    クエリパラメータ q に基づいてプロンプトを検索するエンドポイント。
    API endpoint to search public prompts by query parameter `q`.
    """
    # クエリパラメータから検索語句、プロンプトタイプ、ページ数、表示数を取得
    # Retrieve search query, prompt type, page, and per_page parameters.
    query = request.query_params.get('q', '').strip()
    prompt_type = _normalize_prompt_type_filter(request.query_params.get("prompt_type"))
    page = _parse_positive_int(request.query_params.get("page"), SEARCH_DEFAULT_PAGE)
    per_page = _parse_positive_int(
        request.query_params.get("per_page"),
        SEARCH_DEFAULT_PER_PAGE,
    )
    # セッションから現在ログイン中のユーザーIDを取得
    # Fetch logged-in user's ID from session.
    session = getattr(request, "session", {}) or {}
    user_id = session.get("user_id")
    try:
        # 非ブロッキングスレッドプールでDB検索処理を実行
        # Run DB lookup in the blocking thread pool safely.
        payload = await run_blocking(_search_public_prompts, query, page, per_page, user_id, prompt_type)
        return jsonify({"status": "success", **payload})
    except Exception:
        # エラー発生時はログに記録し、500内部サーバーエラーを返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to search public prompts.",
        )
