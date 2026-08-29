"""Public prompt search endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

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


search_bp = APIRouter(prefix="/search")
logger = logging.getLogger(__name__)

SEARCH_DEFAULT_PAGE = 1
SEARCH_DEFAULT_PER_PAGE = 20
SEARCH_MAX_PER_PAGE = 100
SEARCH_PROMPT_TYPES = {"text", "image", "skill"}


def _parse_positive_int(raw_value: str | None, default: int) -> int:
    try:
        value = int(str(raw_value or "").strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _normalize_search_prompt_row(row: dict[str, Any]) -> dict[str, Any]:
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
    return prompt


def _normalize_prompt_type_filter(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in SEARCH_PROMPT_TYPES else None


def _normalize_content_format_filter(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw or raw == "all":
        return None
    return raw if raw in CONTENT_FORMATS else None


def _normalize_media_type_filter(value: str | None) -> str | None:
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
