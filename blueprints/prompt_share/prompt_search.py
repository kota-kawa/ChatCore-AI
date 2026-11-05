"""公開プロンプトの検索 API（/search/prompts）。文字一致に、埋め込みベクトルによる意味検索を組み合わせる。

Public prompt search endpoints (/search/prompts). Combines lexical matching with embedding-based semantic search.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from services.async_utils import run_blocking
from services.embeddings import embeddings_available, generate_embedding
from services.i18n import get_request_locale
from services.prompt_categories import category_keys_matching
from services.prompt_types import (
    CONTENT_FORMATS,
    MEDIA_TYPES,
    legacy_prompt_type_to_axes,
    serialize_axes,
)
from services.shared_content_service import SharedContentService
from services.web import jsonify, log_and_internal_server_error

# 公開プロンプト検索用のルーター（ログイン不要。ログイン中ならいいね等の状態も付与する）。
# Router for public prompt search (no login required; per-user flags such as "liked" are included when signed in).
search_bp = APIRouter(prefix="/search")
logger = logging.getLogger(__name__)

# ページング既定値と上限、および許可する旧プロンプト種別。
# Paging defaults and limits, and the allowed legacy prompt types.
SEARCH_DEFAULT_PAGE = 1
SEARCH_DEFAULT_PER_PAGE = 20
SEARCH_MAX_PER_PAGE = 100
SEARCH_PROMPT_TYPES = {"text", "image", "skill"}
# 1 文字の検索語は意味を持たないので埋め込みを作らず、文字一致だけで探す。
# A single character carries no meaning to embed; those searches stay lexical.
SEARCH_SEMANTIC_MIN_QUERY_CHARS = 2
# 検索結果の並び替えにだけ使う列。API の応答には出さない。
# Columns used only to order results; never part of the API response.
SEARCH_RANKING_COLUMNS = ("lexical_rank", "semantic_distance")


def _parse_positive_int(raw_value: str | None, default: int) -> int:
    """クエリ文字列を正の整数に変換する。変換できない・0 以下なら既定値を返す。

    Parse a query-string value as a positive int, falling back to the default when invalid or not positive.
    """
    try:
        value = int(str(raw_value or "").strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _normalize_search_prompt_row(row: dict[str, Any]) -> dict[str, Any]:
    """検索結果の DB 行を API 出力用に整える。

    日時は ISO 文字列、カウントは整数、フラグは bool にそろえ、スキルのスクリプトを補い、並び替え専用の列は取り除く。

    Normalize a search-result DB row for API output: ISO datetimes, int counts, bool flags, a filled-in skill script,
    and ranking-only columns removed.
    """
    prompt = dict(row)
    created_at = prompt.get("created_at")
    if hasattr(created_at, "isoformat"):
        prompt["created_at"] = created_at.isoformat()
    prompt["description"] = str(prompt.get("description") or "")
    prompt.update(serialize_axes(prompt))
    resources = prompt.get("resources")
    prompt["resources"] = resources if isinstance(resources, list) else []
    if not prompt.get("skill_python_script") and prompt.get("resource_python_script"):
        prompt["skill_python_script"] = str(prompt["resource_python_script"])
    if not prompt.get("skill_python_script"):
        for resource in prompt["resources"]:
            if isinstance(resource, dict) and resource.get("path") == "scripts/main.py":
                if isinstance(resource.get("content"), str):
                    prompt["skill_python_script"] = resource["content"]
                break
    prompt.pop("resource_python_script", None)
    prompt["liked"] = bool(prompt.get("liked"))
    prompt["used_in_chat"] = bool(prompt.get("used_in_chat"))
    prompt["added_to_skills"] = bool(prompt.get("added_to_skills"))
    prompt["comment_count"] = int(prompt.get("comment_count") or 0)
    prompt["view_count"] = int(prompt.get("view_count") or 0)
    prompt["like_count"] = int(prompt.get("like_count") or 0)
    featured_at = prompt.get("featured_at")
    if hasattr(featured_at, "isoformat"):
        prompt["featured_at"] = featured_at.isoformat()
    for column in SEARCH_RANKING_COLUMNS:
        prompt.pop(column, None)
    return prompt


async def _embed_search_query(query: str) -> list[float] | None:
    """検索語をイベントループの外でベクトルに変換する。短すぎる語や埋め込みが使えない場合は None を返し、文字一致だけで探す。

    Turn the query into a vector off the event loop, or None to stay lexical.

    ``generate_embedding`` already logs and latches provider failures, so a None here
    simply means the search falls back to word matching for this request.
    """
    normalized = query.strip()
    if len(normalized) < SEARCH_SEMANTIC_MIN_QUERY_CHARS or not embeddings_available():
        return None
    return await run_blocking(generate_embedding, normalized)


def _normalize_prompt_type_filter(value: str | None) -> str | None:
    """旧 prompt_type の絞り込み値を検証し、未知の値は None（絞り込みなし）にする。

    Validate the legacy prompt_type filter value; unknown values become None (no filter).
    """
    normalized = str(value or "").strip().lower()
    return normalized if normalized in SEARCH_PROMPT_TYPES else None


def _normalize_content_format_filter(value: str | None) -> str | None:
    """content_format の絞り込み値を検証し、空・"all"・未知の値は None（絞り込みなし）にする。

    Validate the content_format filter; empty, "all" and unknown values become None (no filter).
    """
    raw = str(value or "").strip().lower()
    if not raw or raw == "all":
        return None
    return raw if raw in CONTENT_FORMATS else None


def _normalize_media_type_filter(value: str | None) -> str | None:
    """media_type の絞り込み値を検証し、空・"all"・未知の値は None（絞り込みなし）にする。

    Validate the media_type filter; empty, "all" and unknown values become None (no filter).
    """
    raw = str(value or "").strip().lower()
    if not raw or raw == "all":
        return None
    return raw if raw in MEDIA_TYPES else None


async def _search_public_prompts(
    query: str,
    page: int,
    per_page: int,
    user_id: int | None = None,
    prompt_type: str | None = None,
    content_format: str | None = None,
    media_type: str | None = None,
    include_total: bool = True,
    locale: str = "ja",
) -> dict[str, Any]:
    """公開プロンプトを検索し、ページ情報つきの結果を返す。

    空の検索語は検索せず空の結果を返す。旧 prompt_type は、新しい 2 軸（content_format / media_type）の指定が無いときだけ軸へ変換する。
    include_total が False の場合は総数を数えないため total と total_pages は None になりうる。

    Search public prompts and return results with pagination.

    An empty query returns an empty result without searching. The legacy prompt_type is converted to the two newer axes
    (content_format / media_type) only when neither axis is given. With include_total False, total and total_pages may be None.
    """
    page = max(int(page), SEARCH_DEFAULT_PAGE)
    per_page = max(1, min(int(per_page), SEARCH_MAX_PER_PAGE))
    if not str(query or "").strip():
        return {
            "prompts": [],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": 0,
                "total_pages": 0,
                "has_next": False,
                "has_prev": page > SEARCH_DEFAULT_PAGE,
            },
        }
    prompt_type_filter = _normalize_prompt_type_filter(prompt_type)
    content_format_filter = _normalize_content_format_filter(content_format)
    media_type_filter = _normalize_media_type_filter(media_type)
    if prompt_type_filter and not content_format_filter and not media_type_filter:
        content_format_filter, media_type_filter = legacy_prompt_type_to_axes(prompt_type_filter)
    data = await SharedContentService(public_base_url="").search_public_prompts(
        query=query,
        page=page,
        per_page=per_page,
        user_id=user_id,
        content_format=content_format_filter,
        media_type=media_type_filter,
        include_total=include_total,
        locale=locale,
        matching_category_keys=category_keys_matching(query),
        query_embedding=await _embed_search_query(query),
    )
    rows = data["rows"]
    total = data["total"]
    return {
        "prompts": [_normalize_search_prompt_row(row) for row in rows],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": ((total + per_page - 1) // per_page if total is not None and total > 0 else None),
            "has_next": data["has_next"],
            "has_prev": page > SEARCH_DEFAULT_PAGE,
        },
    }


@search_bp.get("/prompts", name="search.search_prompts")
async def search_prompts(request: Request):
    # クエリ文字列（q・page・per_page・各種フィルタ）から公開プロンプトを検索して JSON で返す。
    #
    # Search public prompts from the query string (q, page, per_page and filters) and return JSON.
    query = request.query_params.get("q", "").strip()
    include_total = request.query_params.get("include_total", "1").strip().lower() not in {"0", "false", "no"}
    page = _parse_positive_int(request.query_params.get("page"), SEARCH_DEFAULT_PAGE)
    per_page = _parse_positive_int(request.query_params.get("per_page"), SEARCH_DEFAULT_PER_PAGE)
    session = getattr(request, "session", {}) or {}
    try:
        payload = await _search_public_prompts(
            query,
            page,
            per_page,
            session.get("user_id"),
            request.query_params.get("prompt_type"),
            request.query_params.get("content_format"),
            request.query_params.get("media_type"),
            include_total,
            get_request_locale(request),
        )
        return jsonify({"status": "success", **payload})
    except Exception:
        return log_and_internal_server_error(logger, "Failed to search public prompts.")
