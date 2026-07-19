"""Owner-scoped personal context vault operations shared by web routes and MCP tools.

Facts are small, typed pieces of personal context (preferences, profile, project
context, past decisions) that a user can serve to any MCP client. DTO conversion is
allowlisted so raw database rows never leak through the API surface.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from services.api_errors import ApiServiceError
from services.context_vault_embeddings import schedule_embedding
from services.memo_ai import embeddings_available, generate_embedding
from services.repositories.context_fact_repository import ContextFactRepository
from services.request_models import (
    ContextFactStatus,
    ContextFactType,
    MAX_CONTEXT_FACT_CONTENT_LENGTH,
    MAX_CONTEXT_FACT_TITLE_LENGTH,
)
from services.response_models import (
    ContextDigestGroup,
    ContextDigestResponse,
    ContextFactListResponse,
    ContextFactResponse,
)

logger = logging.getLogger("blueprints.context_vault")

MAX_CONTEXT_LIST_LIMIT = 100
DEFAULT_CONTEXT_LIST_LIMIT = 50
MAX_DIGEST_LIMIT_PER_TYPE = 50
DEFAULT_DIGEST_LIMIT_PER_TYPE = 20
MAX_CONTEXT_SEARCH_LIMIT = 50
DEFAULT_CONTEXT_SEARCH_LIMIT = 20

ContextSearchMode = Literal["keyword", "semantic"]

# get_personal_context のグループ表示順。プロフィール系を先頭に固定する。
# Fixed group order for get_personal_context, leading with profile-oriented types.
_DIGEST_TYPE_ORDER: tuple[str, ...] = (
    "profile",
    "preference",
    "project",
    "decision",
    "reference",
)

_CURSOR_SEPARATOR = "~"


class ContextSearchResult(BaseModel):
    """Bounded search result returned to an authorized MCP client."""

    total: int = Field(ge=0)
    facts: list[ContextFactResponse]


def _repository() -> ContextFactRepository:
    return ContextFactRepository()


def _to_response(fact: dict[str, Any]) -> ContextFactResponse:
    """Build an allowlisted DTO, dropping internal fields such as the raw timestamp."""
    return ContextFactResponse(
        id=int(fact["id"]),
        fact_type=str(fact["fact_type"]),
        title=str(fact.get("title") or ""),
        content=str(fact.get("content") or ""),
        status=str(fact.get("status") or "active"),
        revision=max(int(fact.get("revision") or 1), 1),
        created_at=fact.get("created_at"),
        updated_at=fact.get("updated_at"),
    )


def _encode_cursor(fact: dict[str, Any]) -> str | None:
    updated_at = fact.get("updated_at")
    if not updated_at:
        return None
    return f"{updated_at}{_CURSOR_SEPARATOR}{int(fact['id'])}"


def _decode_cursor(cursor: str | None) -> tuple[datetime, int] | None:
    if not cursor:
        return None
    raw, _, id_part = cursor.rpartition(_CURSOR_SEPARATOR)
    if not raw or not id_part:
        raise ApiServiceError("ページングカーソルが不正です。", 400, status="fail")
    try:
        return datetime.fromisoformat(raw), int(id_part)
    except (TypeError, ValueError) as exc:
        raise ApiServiceError("ページングカーソルが不正です。", 400, status="fail") from exc


def _safe_list_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_CONTEXT_LIST_LIMIT))


def _safe_search_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_CONTEXT_SEARCH_LIMIT))


def list_facts(
    user_id: int,
    *,
    fact_type: ContextFactType | None = None,
    status: ContextFactStatus = "active",
    limit: int = DEFAULT_CONTEXT_LIST_LIMIT,
    cursor: str | None = None,
) -> ContextFactListResponse:
    """List the owner's context facts with keyset pagination."""
    repo = _repository()
    safe_limit = _safe_list_limit(limit)
    decoded = _decode_cursor(cursor)
    before_updated_at = decoded[0] if decoded else None
    before_id = decoded[1] if decoded else None
    # Fetch one extra row to know whether another page exists.
    rows = repo.list_facts(
        user_id,
        fact_type=fact_type,
        status=status,
        limit=safe_limit + 1,
        before_updated_at=before_updated_at,
        before_id=before_id,
    )
    next_cursor: str | None = None
    if len(rows) > safe_limit:
        next_cursor = _encode_cursor(rows[safe_limit - 1])
        rows = rows[:safe_limit]
    return ContextFactListResponse(
        facts=[_to_response(row) for row in rows],
        total_active=repo.count_active(user_id),
        next_cursor=next_cursor,
    )


def get_fact(user_id: int, fact_id: int) -> ContextFactResponse:
    """Load one context fact owned by the authenticated user."""
    return _to_response(_repository().get_fact(user_id, fact_id))


def create_fact(
    user_id: int,
    *,
    fact_type: ContextFactType,
    title: str,
    content: str,
) -> ContextFactResponse:
    """Create a context fact for the authenticated owner and schedule its embedding."""
    fact = _repository().create_fact(
        user_id,
        fact_type=fact_type,
        title=title.strip()[:MAX_CONTEXT_FACT_TITLE_LENGTH],
        content=content.strip()[:MAX_CONTEXT_FACT_CONTENT_LENGTH],
    )
    schedule_embedding(
        int(fact["id"]),
        str(fact["fact_type"]),
        str(fact["title"]),
        str(fact["content"]),
        int(fact["revision"]),
    )
    return _to_response(fact)


def update_fact(
    user_id: int,
    fact_id: int,
    *,
    expected_revision: int,
    title: str | None = None,
    content: str | None = None,
    fact_type: ContextFactType | None = None,
    status: ContextFactStatus | None = None,
) -> ContextFactResponse:
    """Update a context fact only when the caller's revision is still current."""
    fact = _repository().update_fact(
        user_id,
        fact_id,
        expected_revision=expected_revision,
        title=title.strip()[:MAX_CONTEXT_FACT_TITLE_LENGTH] if title is not None else None,
        content=content.strip()[:MAX_CONTEXT_FACT_CONTENT_LENGTH] if content is not None else None,
        fact_type=fact_type,
        status=status,
    )
    # Re-embed when the searchable text changed and the fact remains active.
    if str(fact.get("status")) == "active" and (
        title is not None or content is not None or fact_type is not None
    ):
        schedule_embedding(
            int(fact["id"]),
            str(fact["fact_type"]),
            str(fact["title"]),
            str(fact["content"]),
            int(fact["revision"]),
        )
    return _to_response(fact)


def deprecate_fact(user_id: int, fact_id: int, *, expected_revision: int) -> ContextFactResponse:
    """Deprecate (soft-disable) a context fact, preserving history."""
    return update_fact(
        user_id,
        fact_id,
        expected_revision=expected_revision,
        status="deprecated",
    )


def build_digest(
    user_id: int,
    *,
    limit_per_type: int = DEFAULT_DIGEST_LIMIT_PER_TYPE,
) -> ContextDigestResponse:
    """Build a compact digest of active facts grouped by fact_type."""
    per_type = max(1, min(int(limit_per_type), MAX_DIGEST_LIMIT_PER_TYPE))
    rows = _repository().list_active_for_digest(user_id)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["fact_type"]), []).append(row)

    truncated = False
    groups: list[ContextDigestGroup] = []
    total = 0
    ordered_types = list(_DIGEST_TYPE_ORDER) + [
        fact_type for fact_type in grouped if fact_type not in _DIGEST_TYPE_ORDER
    ]
    for fact_type in ordered_types:
        facts = grouped.get(fact_type)
        if not facts:
            continue
        if len(facts) > per_type:
            truncated = True
            facts = facts[:per_type]
        total += len(facts)
        groups.append(
            ContextDigestGroup(
                fact_type=fact_type,
                facts=[_to_response(fact) for fact in facts],
            )
        )
    return ContextDigestResponse(facts_total=total, truncated=truncated, groups=groups)


def search_facts(
    user_id: int,
    query: str,
    *,
    mode: ContextSearchMode = "keyword",
    limit: int = DEFAULT_CONTEXT_SEARCH_LIMIT,
) -> ContextSearchResult:
    """Search the owner's active facts by keyword or semantic similarity."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ApiServiceError("検索語を指定してください。", 400, status="fail")

    repo = _repository()
    safe_limit = _safe_search_limit(limit)
    rows: list[dict[str, Any]] = []
    if mode == "semantic" and embeddings_available():
        try:
            embedding = generate_embedding(normalized_query)
        except Exception:
            embedding = None
            logger.warning(
                "Failed to generate a context search embedding; using keyword search.",
                exc_info=True,
            )
        if embedding:
            rows = repo.semantic_search(user_id, embedding, limit=safe_limit, status="active")

    if not rows:
        rows = repo.text_search(user_id, normalized_query, limit=safe_limit, status="active")

    return ContextSearchResult(total=len(rows), facts=[_to_response(row) for row in rows])
