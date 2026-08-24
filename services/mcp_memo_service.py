"""Owner-scoped memo operations exposed to the remote MCP server."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.memo_embedding_service import schedule_embedding
from services.repositories.memo_helpers import ensure_title
from services.repositories.memo_repository import (
    fetch_collections,
    fetch_memo_detail,
    fetch_memo_summaries,
    insert_memo,
    update_memo as update_memo_record,
)
from services.api_errors import ApiServiceError
from services.db import session_scope
from services.embeddings import embeddings_available, generate_embedding
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
    return McpMemoSearchResult(
        **_summary_fields(memo),
        excerpt=str(memo.get("excerpt") or ""),
    )


def _to_detail(memo: dict[str, Any]) -> McpMemoDetail:
    return McpMemoDetail(
        **_summary_fields(memo),
        content=str(memo.get("ai_response") or ""),
    )


async def list_memos(
    user_id: int,
    *,
    limit: int = DEFAULT_MCP_MEMO_LIST_LIMIT,
    offset: int = 0,
    sort: MemoSort = "updated",
    include_archived: bool = False,
    only_archived: bool = False,
    collection_id: int | None = None,
    session: AsyncSession | None = None,
) -> McpMemoListResult:
    """List only the authenticated owner's memo titles and safe metadata."""
    result = await fetch_memo_summaries(
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
        session=session,
    )
    return McpMemoListResult(
        total=max(int(result.get("total") or 0), 0),
        memos=[_to_summary(memo) for memo in result.get("memos", [])],
    )


async def search_memos(
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
    session: AsyncSession | None = None,
) -> McpMemoSearchListResult:
    """Search the authenticated owner's memo titles and bodies."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ApiServiceError("検索語を指定してください。", 400, status="fail")

    semantic_embedding: list[float] | None = None
    if mode == "semantic" and embeddings_available():
        try:
            semantic_embedding = await asyncio.to_thread(
                generate_embedding,
                normalized_query,
            )
        except Exception:
            logger.warning(
                "Failed to generate an MCP memo search embedding; using keyword search.",
                exc_info=True,
            )

    result = await fetch_memo_summaries(
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
        session=session,
    )
    return McpMemoSearchListResult(
        total=max(int(result.get("total") or 0), 0),
        memos=[_to_search_result(memo) for memo in result.get("memos", [])],
    )


async def get_memo(
    user_id: int,
    memo_id: int,
    *,
    session: AsyncSession | None = None,
) -> McpMemoDetail:
    """Load one private memo owned by the authenticated user."""
    return _to_detail(await fetch_memo_detail(user_id, memo_id, session=session))


async def update_memo(
    user_id: int,
    memo_id: int,
    payload: McpMemoUpdateRequest,
    *,
    session: AsyncSession | None = None,
) -> McpMemoDetail:
    """Update title/content only when the caller's revision is still current."""
    memo = await update_memo_record(
        user_id,
        memo_id,
        title=payload.title,
        ai_response=payload.content,
        collection_id=None,
        clear_collection=False,
        expected_revision=payload.expected_revision,
        allow_shared_content_change=payload.allow_shared_content_change,
        session=session,
    )
    if session is None:
        schedule_embedding(
            memo_id,
            str(memo.get("title") or ""),
            str(memo.get("ai_response") or ""),
            int(memo.get("revision") or 1),
        )
    return _to_detail(memo)


async def create_memo(
    user_id: int,
    payload: McpMemoCreateRequest,
    *,
    session: AsyncSession | None = None,
) -> McpMemoDetail:
    """Create a private memo for the authenticated owner."""
    title = ensure_title(payload.content, payload.title)

    async def operation(db: AsyncSession) -> McpMemoDetail:
        memo_id = await insert_memo(
            user_id,
            payload.content,
            title,
            None,
            session=db,
        )
        if memo_id is None:
            raise ApiServiceError("メモを作成できませんでした。", 500, status="fail")
        return _to_detail(await fetch_memo_detail(user_id, memo_id, session=db))

    if session is not None:
        return await operation(session)
    async with session_scope() as db:
        async with db.begin():
            memo = await operation(db)
    schedule_embedding(
        memo.id,
        title,
        payload.content,
        memo.revision,
    )
    return memo


async def append_memo(
    user_id: int,
    memo_id: int,
    payload: McpMemoAppendRequest,
    *,
    session: AsyncSession | None = None,
) -> McpMemoDetail:
    """Append text without silently overwriting a concurrently changed memo."""
    async def operation(db: AsyncSession) -> McpMemoDetail:
        current = await fetch_memo_detail(user_id, memo_id, session=db)
        current_content = str(current.get("ai_response") or "")
        appended_content = f"{current_content}{payload.separator}{payload.text}"
        if len(appended_content) > MAX_MEMO_STORED_CONTENT_LENGTH:
            raise ApiServiceError(
                f"追記後のメモ本文は{MAX_MEMO_STORED_CONTENT_LENGTH}文字以内にしてください。",
                400,
                status="fail",
            )
        memo = await update_memo_record(
            user_id,
            memo_id,
            title=None,
            ai_response=appended_content,
            collection_id=None,
            clear_collection=False,
            expected_revision=payload.expected_revision,
            allow_shared_content_change=payload.allow_shared_content_change,
            session=db,
        )
        return _to_detail(memo)

    if session is not None:
        return await operation(session)
    async with session_scope() as db:
        async with db.begin():
            memo = await operation(db)
    schedule_embedding(
        memo.id,
        memo.title,
        memo.content,
        memo.revision,
    )
    return memo


async def list_collections(
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> McpMemoCollectionListResult:
    """List collection metadata owned by the authenticated user."""
    collections = await fetch_collections(user_id, session=session)
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
