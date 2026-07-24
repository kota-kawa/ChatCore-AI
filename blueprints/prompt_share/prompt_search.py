import logging
from typing import Any

from fastapi import APIRouter, Request

from services.async_utils import run_blocking
from services.db import get_db_connection  # 既存の DB 接続関数を利用
# Reuse the shared DB connection helper.
from services.prompt_categories import category_keys_matching
from services.prompt_types import (
    CONTENT_FORMATS,
    MEDIA_TYPES,
    legacy_prompt_type_to_axes,
    serialize_axes,
)
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

# Count queries are only needed for the initial page; later pages use LIMIT + 1.
SEARCH_NEXT_PAGE_SIZE = 1

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

    # 2軸フィールド (content_format/media_type/attributes/attachments) を正準化し、
    # 後方互換の派生フィールド (prompt_type/reference_image_url/skill_*) を付与する。
    # Normalize the two-axis fields and attach derived legacy fields.
    prompt.update(serialize_axes(prompt))
    resources = prompt.get("resources")
    prompt["resources"] = resources if isinstance(resources, list) else []
    if not prompt.get("skill_python_script") and prompt.get("resource_python_script"):
        prompt["skill_python_script"] = str(prompt["resource_python_script"])
    if not prompt.get("skill_python_script"):
        for resource in prompt["resources"]:
            if (
                isinstance(resource, dict)
                and resource.get("path") == "scripts/main.py"
                and isinstance(resource.get("content"), str)
            ):
                prompt["skill_python_script"] = resource["content"]
                break
    prompt.pop("resource_python_script", None)

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


def _normalize_content_format_filter(value):
    """
    指定されたフォーマット軸の値が許可されたセットに含まれるか検証し、正規化する。
    Validate and normalize a content_format filter value.
    """
    raw = str(value or "").strip().lower()
    if not raw or raw == "all":
        return None
    return raw if raw in CONTENT_FORMATS else None


def _normalize_media_type_filter(value):
    """
    指定されたメディア軸の値が許可されたセットに含まれるか検証し、正規化する。
    Validate and normalize a media_type filter value.
    """
    raw = str(value or "").strip().lower()
    if not raw or raw == "all":
        return None
    return raw if raw in MEDIA_TYPES else None


# 公開プロンプトの部分一致検索をデータベースクエリとして実行する関数
# Database lookup function to search public prompts by keywords and optional types.
def _search_public_prompts(
    query,
    page,
    per_page,
    user_id=None,
    prompt_type=None,
    content_format=None,
    media_type=None,
    include_total=True,
):
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
        
        # 2軸フィルタ指定の検証と追加SQL文の組み立て。旧 prompt_type は互換入力として2軸へ変換する。
        # Validate and construct optional two-axis SQL segments. Legacy prompt_type maps to axes.
        prompt_type_filter = _normalize_prompt_type_filter(prompt_type)
        content_format_filter = _normalize_content_format_filter(content_format)
        media_type_filter = _normalize_media_type_filter(media_type)
        if prompt_type_filter and not content_format_filter and not media_type_filter:
            legacy_content_format, legacy_media_type = legacy_prompt_type_to_axes(prompt_type_filter)
            content_format_filter = legacy_content_format
            media_type_filter = legacy_media_type

        select_axis_conditions = []
        count_axis_conditions = []
        count_filter_params = []
        search_filter_params = []
        if content_format_filter:
            select_axis_conditions.append("AND p.content_format = %s")
            count_axis_conditions.append("AND content_format = %s")
            count_filter_params.append(content_format_filter)
            search_filter_params.append(content_format_filter)
        if media_type_filter:
            select_axis_conditions.append("AND p.media_type = %s")
            count_axis_conditions.append("AND media_type = %s")
            count_filter_params.append(media_type_filter)
            search_filter_params.append(media_type_filter)

        select_axis_condition = "\n              ".join(select_axis_conditions)
        count_axis_condition = "\n              ".join(count_axis_conditions)
        
        # まずページ対象を確定してから、各結果に必要な派生情報だけを取得する。
        # Select the page first, then calculate interaction and comment metadata only for its rows.
        sql = f"""
            WITH matched_prompts AS (
              SELECT
                p.id,
                p.title,
                p.category,
                p.content,
                COALESCE(u.username, p.author, 'ユーザー') AS author,
                p.input_examples,
                p.output_examples,
                p.content_format,
                p.media_type,
                p.attributes,
                p.attachments,
                COALESCE(
                  (
                    SELECT jsonb_agg(
                      jsonb_build_object(
                        'id', pr.id,
                        'path', pr.path,
                        'role', pr.role,
                        'language', COALESCE(pr.language, ''),
                        'media_type', pr.media_type,
                        'size_bytes', pr.size_bytes,
                        'sha256', pr.sha256,
                        'sort_order', pr.sort_order
                      )
                      ORDER BY pr.sort_order, pr.id
                    )
                    FROM prompt_resources AS pr
                    WHERE pr.prompt_id = p.id
                  ),
                  '[]'::jsonb
                ) AS resources,
                COALESCE(
                  (
                    SELECT pr.text_content
                    FROM prompt_resources AS pr
                    WHERE pr.prompt_id = p.id
                      AND lower(pr.path) = 'scripts/main.py'
                    LIMIT 1
                  ),
                  ''
                ) AS resource_python_script,
                p.created_at
              FROM prompts AS p
              LEFT JOIN users AS u
                ON u.id = p.user_id
              WHERE p.is_public = TRUE
                AND p.deleted_at IS NULL
                {select_axis_condition}
                AND (
                  p.title LIKE %s OR
                  p.content LIKE %s OR
                  p.category = ANY(%s::text[]) OR
                  p.author LIKE %s OR
                  u.username LIKE %s
                )
              ORDER BY p.created_at DESC, p.id DESC
              LIMIT %s
              OFFSET %s
            )
            SELECT
              p.*,
              COALESCE(pc.comment_count, 0) AS comment_count,
              EXISTS (
                SELECT 1
                FROM prompt_likes AS pl
                WHERE pl.user_id = %s
                  AND pl.prompt_id = p.id
              ) AS liked,
              EXISTS (
                SELECT 1
                FROM task_with_examples AS used_tasks
                WHERE used_tasks.user_id = %s
                  AND used_tasks.deleted_at IS NULL
                  AND (
                    used_tasks.source_prompt_id = p.id
                    OR (
                      used_tasks.source_prompt_id IS NULL
                      AND used_tasks.name = p.title
                    )
                  )
              ) AS used_in_chat
            FROM matched_prompts AS p
            LEFT JOIN LATERAL (
              SELECT COUNT(*) AS comment_count
              FROM prompt_comments
              WHERE deleted_at IS NULL
                AND hidden_by_reports_at IS NULL
                AND prompt_id = p.id
            ) AS pc
              ON TRUE
            ORDER BY p.created_at DESC, p.id DESC
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
              {count_axis_condition}
              AND (
                p.title LIKE %s OR
                p.content LIKE %s OR
                p.category = ANY(%s::text[]) OR
                p.author LIKE %s OR
                u.username LIKE %s
              )
        """
        # LIKE検索用のワイルドカード付きパターンを作成
        # Create a search pattern with wildcards for LIKE operator.
        like_query = f"%{query}%"
        # カテゴリはキーで保存されるため、日本語ラベルへの部分一致をキー集合に解決してから照合する。
        # Categories are stored as keys, so resolve a label substring match into the matching keys.
        matched_category_keys = category_keys_matching(query)
        count_params = list(count_filter_params)
        count_params.extend([like_query, like_query, matched_category_keys, like_query, like_query])
        total = None
        if include_total:
            # 件数取得は初回ページだけに限定し、追加読み込み時の全件集計を避ける。
            # Only the initial page needs an exact count; later pages use LIMIT + 1.
            cursor.execute(count_sql, tuple(count_params))
            count_row = cursor.fetchone() or {}
            total = int(count_row.get("total") or 0)

        # 検索パラメータの構築
        # Build query arguments list.
        search_params = list(search_filter_params)
        search_params.extend([
            like_query,
            like_query,
            matched_category_keys,
            like_query,
            like_query,
            per_page + SEARCH_NEXT_PAGE_SIZE,
            offset,
            user_id,
            user_id,
        ])
        
        # 検索結果レコードの取得実行
        # Execute query retrieval.
        cursor.execute(
            sql,
            tuple(search_params),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        has_next = (
            page * per_page < total
            if total is not None
            else len(rows) > per_page
        )
        rows = rows[:per_page]
        total_pages = (
            (total + per_page - 1) // per_page if total is not None and total > 0 else None
        )
        return {
            "prompts": [_normalize_search_prompt_row(row) for row in rows],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "has_next": has_next,
                "has_prev": page > SEARCH_DEFAULT_PAGE,
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
    content_format = _normalize_content_format_filter(request.query_params.get("content_format"))
    media_type = _normalize_media_type_filter(request.query_params.get("media_type"))
    include_total = request.query_params.get("include_total", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
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
        payload = await run_blocking(
            _search_public_prompts,
            query,
            page,
            per_page,
            user_id,
            prompt_type,
            content_format,
            media_type,
            include_total,
        )
        return jsonify({"status": "success", **payload})
    except Exception:
        # エラー発生時はログに記録し、500内部サーバーエラーを返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to search public prompts.",
        )
