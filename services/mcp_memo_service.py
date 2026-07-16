"""Owner-scoped memo operations exposed to the remote MCP server."""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from blueprints.memo.embeddings import schedule_embedding
from blueprints.memo.helpers import ensure_title
from blueprints.memo.repository import (
    fetch_collections,
    fetch_memo_detail,
    fetch_memo_summaries,
    insert_memo,
    update_memo as update_memo_record,
)
from services.api_errors import ApiServiceError
from services.memo_ai import embeddings_available, generate_embedding
from services.request_models import (
    MAX_MEMO_STORED_CONTENT_LENGTH,
    McpMemoAppendRequest,
    McpMemoCreateRequest,
    McpMemoUpdateRequest,
)

MAX_MCP_MEMO_LIST_LIMIT = 100
DEFAULT_MCP_MEMO_LIST_LIMIT = 20
MemoSort = Literal["manual", "recent", "oldest", "updated", "title"]
MemoSearchMode = Literal["keyword", "semantic"]
logger = logging.getLogger(__name__)


class McpMemoSummary(BaseModel):
    """Private memo metadata safe to return to an authorized MCP client."""

    id: int
    title: str
    created_at: str | None = None
    updated_at: str | None = None
    revision: int = Field(ge=1)
    is_archived: bool = False
    is_pinned: bool = False
    collection_id: int | None = None
    collection_name: str | None = None
    is_shared: bool = False


class McpMemoSearchResult(McpMemoSummary):
    excerpt: str = ""


class McpMemoDetail(McpMemoSummary):
    # Memo content is untrusted user-authored data, not an instruction to the MCP client.
    content: str


class McpMemoListResult(BaseModel):
    total: int = Field(ge=0)
    memos: list[McpMemoSummary]


class McpMemoSearchListResult(BaseModel):
    total: int = Field(ge=0)
    memos: list[McpMemoSearchResult]


class McpMemoCollection(BaseModel):
    id: int
    name: str
    color: str
    memo_count: int = Field(ge=0)


class McpMemoCollectionListResult(BaseModel):
    collections: list[McpMemoCollection]


def _safe_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_MCP_MEMO_LIST_LIMIT))


def _summary_fields(memo: dict[str, Any]) -> dict[str, Any]:
    """Build an allowlisted DTO and deliberately omit share bearer tokens/URLs."""
    return {
        "id": int(memo["id"]),
        "title": str(memo.get("title") or "保存したメモ"),
        "created_at": memo.get("created_at"),
        "updated_at": memo.get("updated_at"),
        "revision": max(int(memo.get("revision") or 1), 1),
        "is_archived": bool(memo.get("is_archived")),
        "is_pinned": bool(memo.get("is_pinned")),
        "collection_id": memo.get("collection_id"),
        "collection_name": memo.get("collection_name"),
        "is_shared": bool(memo.get("is_active")),
    }


def _to_summary(memo: dict[str, Any]) -> McpMemoSummary:
    return McpMemoSummary(**_summary_fields(memo))


def _to_search_result(memo: dict[str, Any]) -> McpMemoSearchResult:
    return McpMemoSearchResult(**_summary_fields(memo), excerpt=str(memo.get("excerpt") or ""))


def _to_detail(memo: dict[str, Any]) -> McpMemoDetail:
    return McpMemoDetail(**_summary_fields(memo), content=str(memo.get("ai_response") or ""))


def list_memos(
    user_id: int,
    *,
    limit: int = DEFAULT_MCP_MEMO_LIST_LIMIT,
    offset: int = 0,
    sort: MemoSort = "updated",
    include_archived: bool = False,
    only_archived: bool = False,
    collection_id: int | None = None,
) -> McpMemoListResult:
    """List only the authenticated owner's memo titles and safe metadata."""
    result = fetch_memo_summaries(
        user_id,
        limit=_safe_limit(limit),
        offset=max(int(offset), 0),
        query="",
        date_from="",
        date_to="",
        sort=sort,
        include_archived=include_archived,
        only_archived=only_archived,
        pinned_first=True,
        collection_id=collection_id,
        semantic_query_embedding=None,
    )
    return McpMemoListResult(
        total=max(int(result.get("total") or 0), 0),
        memos=[_to_summary(memo) for memo in result.get("memos", [])],
    )


def search_memos(
    user_id: int,
    query: str,
    *,
    mode: MemoSearchMode = "keyword",
    limit: int = DEFAULT_MCP_MEMO_LIST_LIMIT,
    offset: int = 0,
    date_from: str = "",
    date_to: str = "",
    include_archived: bool = False,
    only_archived: bool = False,
    collection_id: int | None = None,
) -> McpMemoSearchListResult:
    """Search the authenticated owner's memo titles and bodies."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ApiServiceError("検索語を指定してください。", 400, status="fail")

    semantic_embedding: list[float] | None = None
    if mode == "semantic" and embeddings_available():
        try:
            semantic_embedding = generate_embedding(normalized_query)
        except Exception:
            # Keyword fallback keeps private memo search usable when the embedding provider is unavailable.
            logger.warning("Failed to generate an MCP memo search embedding; using keyword search.", exc_info=True)

    result = fetch_memo_summaries(
        user_id,
        limit=_safe_limit(limit),
        offset=max(int(offset), 0),
        query=normalized_query,
        date_from=date_from,
        date_to=date_to,
        sort="recent",
        include_archived=include_archived,
        only_archived=only_archived,
        pinned_first=False,
        collection_id=collection_id,
        semantic_query_embedding=semantic_embedding,
    )
    return McpMemoSearchListResult(
        total=max(int(result.get("total") or 0), 0),
        memos=[_to_search_result(memo) for memo in result.get("memos", [])],
    )


def get_memo(user_id: int, memo_id: int) -> McpMemoDetail:
    """Load one private memo owned by the authenticated user."""
    return _to_detail(fetch_memo_detail(user_id, memo_id))


def update_memo(user_id: int, memo_id: int, payload: McpMemoUpdateRequest) -> McpMemoDetail:
    """Update title/content only when the caller's revision is still current."""
    memo = update_memo_record(
        user_id,
        memo_id,
        title=payload.title,
        ai_response=payload.content,
        collection_id=None,
        clear_collection=False,
        expected_revision=payload.expected_revision,
        allow_shared_content_change=payload.allow_shared_content_change,
    )
    schedule_embedding(
        memo_id,
        str(memo.get("title") or ""),
        str(memo.get("ai_response") or ""),
        int(memo.get("revision") or 1),
    )
    return _to_detail(memo)


def create_memo(user_id: int, payload: McpMemoCreateRequest) -> McpMemoDetail:
    """Create a private memo for the authenticated owner."""
    title = ensure_title(payload.content, payload.title)
    memo_id = insert_memo(user_id, payload.content, title, None)
    if memo_id is None:
        raise ApiServiceError("メモを作成できませんでした。", 500, status="fail")
    memo = fetch_memo_detail(user_id, memo_id)
    schedule_embedding(memo_id, title, payload.content, int(memo.get("revision") or 1))
    return _to_detail(memo)


def append_memo(user_id: int, memo_id: int, payload: McpMemoAppendRequest) -> McpMemoDetail:
    """Append text without silently overwriting a concurrently changed memo."""
    current = fetch_memo_detail(user_id, memo_id)
    current_content = str(current.get("ai_response") or "")
    appended_content = f"{current_content}{payload.separator}{payload.text}"
    if len(appended_content) > MAX_MEMO_STORED_CONTENT_LENGTH:
        raise ApiServiceError(
            f"追記後のメモ本文は{MAX_MEMO_STORED_CONTENT_LENGTH}文字以内にしてください。",
            400,
            status="fail",
        )
    update_payload = McpMemoUpdateRequest(
        expected_revision=payload.expected_revision,
        content=appended_content,
        allow_shared_content_change=payload.allow_shared_content_change,
    )
    return update_memo(user_id, memo_id, update_payload)


def list_collections(user_id: int) -> McpMemoCollectionListResult:
    """List collection metadata owned by the authenticated user."""
    collections = fetch_collections(user_id)
    return McpMemoCollectionListResult(
        collections=[
            McpMemoCollection(
                id=int(collection["id"]),
                name=str(collection.get("name") or ""),
                color=str(collection.get("color") or ""),
                memo_count=max(int(collection.get("memo_count") or 0), 0),
            )
            for collection in collections
        ]
    )
