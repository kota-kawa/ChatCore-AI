"""Owner-scoped personal context vault operations shared by web routes and MCP tools.

Facts are small, typed pieces of personal context (preferences, profile, project
context, past decisions) that a user can serve to any MCP client. DTO conversion is
allowlisted so raw database rows never leak through the API surface.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, Field

from services.api_errors import ApiServiceError
from services.context_vault_embeddings import schedule_embedding
from services.memo_ai import embeddings_available, generate_embedding
from services.repositories.context_fact_repository import ContextFactRepository
from services.request_models import (
    ContextFactStatus,
    ContextFactSourceKind,
    ContextFactType,
    DEFAULT_CONTEXT_FACT_IMPORTANCE,
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
MIN_DIGEST_MAX_CHARS = 2_000
MAX_DIGEST_MAX_CHARS = 20_000
DEFAULT_DIGEST_MAX_CHARS = 12_000
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
    importance = fact.get("importance")
    return ContextFactResponse(
        id=int(fact["id"]),
        fact_type=str(fact["fact_type"]),
        title=str(fact.get("title") or ""),
        content=str(fact.get("content") or ""),
        status=str(fact.get("status") or "active"),
        revision=max(int(fact.get("revision") or 1), 1),
        source_kind=str(fact.get("source_kind") or "manual"),
        importance=max(0, min(int(importance if importance is not None else 50), 100)),
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
    importance: int = DEFAULT_CONTEXT_FACT_IMPORTANCE,
    source_kind: ContextFactSourceKind = "manual",
    source_ref: str | None = None,
    source_client_id: str | None = None,
    idempotency_key: str | None = None,
) -> ContextFactResponse:
    """Create a context fact for the authenticated owner and schedule its embedding."""
    normalized_title = title.strip()[:MAX_CONTEXT_FACT_TITLE_LENGTH]
    normalized_content = content.strip()[:MAX_CONTEXT_FACT_CONTENT_LENGTH]
    normalized_importance = max(0, min(int(importance), 100))
    normalized_source_ref = source_ref.strip()[:500] if source_ref else None
    idempotency_key_hash: str | None = None
    idempotency_payload_hash: str | None = None
    if idempotency_key is not None:
        idempotency_key_hash = sha256(
            f"{user_id}\0{source_kind}\0{source_client_id or ''}\0{idempotency_key}".encode(
                "utf-8"
            )
        ).hexdigest()
        canonical_payload = json.dumps(
            {
                "content": normalized_content,
                "fact_type": fact_type,
                "importance": normalized_importance,
                "source_kind": source_kind,
                "source_ref": normalized_source_ref,
                "title": normalized_title,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        idempotency_payload_hash = sha256(canonical_payload.encode("utf-8")).hexdigest()

    fact = _repository().create_fact(
        user_id,
        fact_type=fact_type,
        title=normalized_title,
        content=normalized_content,
        source_kind=source_kind,
        source_ref=normalized_source_ref,
        source_client_id=source_client_id,
        importance=normalized_importance,
        idempotency_key_hash=idempotency_key_hash,
        idempotency_payload_hash=idempotency_payload_hash,
    )
    if not fact.get("_idempotent_replay"):
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
    importance: int | None = None,
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
        importance=(max(0, min(int(importance), 100)) if importance is not None else None),
    )
    # Every active revision gets an embedding task, even when only metadata
    # changed. A task for the previous revision may still be in flight and its
    # revision-guarded write will then be rejected. Scheduling the returned
    # snapshot prevents that race from leaving the latest revision without a
    # vector. It also regenerates from edits made while deprecated when a fact is
    # restored with a status-only update.
    if str(fact.get("status")) == "active":
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
    max_chars: int = DEFAULT_DIGEST_MAX_CHARS,
) -> ContextDigestResponse:
    """Build an importance-first digest bounded by fact count and serialized size."""
    per_type = max(1, min(int(limit_per_type), MAX_DIGEST_LIMIT_PER_TYPE))
    char_budget = max(MIN_DIGEST_MAX_CHARS, min(int(max_chars), MAX_DIGEST_MAX_CHARS))
    rows = _repository().list_active_for_digest(user_id)
    total_active = len(rows)

    # Allocate the shared response budget to the most important facts first. The
    # timestamp and id preserve deterministic recency ordering for equal importance.
    prioritized = sorted(
        rows,
        key=lambda fact: (
            int(fact.get("importance") if fact.get("importance") is not None else 50),
            str(fact.get("updated_at") or ""),
            int(fact["id"]),
        ),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    counts_by_type: dict[str, int] = {}

    def response_for(candidate_rows: list[dict[str, Any]]) -> ContextDigestResponse:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidate_rows:
            grouped.setdefault(str(candidate["fact_type"]), []).append(candidate)
        ordered_types = list(_DIGEST_TYPE_ORDER) + [
            fact_type for fact_type in grouped if fact_type not in _DIGEST_TYPE_ORDER
        ]
        groups = [
            ContextDigestGroup(
                fact_type=fact_type,
                facts=[_to_response(fact) for fact in grouped[fact_type]],
            )
            for fact_type in ordered_types
            if grouped.get(fact_type)
        ]
        returned_count = len(candidate_rows)
        omitted_count = total_active - returned_count
        return ContextDigestResponse(
            # facts_total historically meant the number returned; keep that contract.
            facts_total=returned_count,
            total_active=total_active,
            returned_count=returned_count,
            omitted_count=omitted_count,
            truncated=omitted_count > 0,
            groups=groups,
        )

    for row in prioritized:
        fact_type = str(row["fact_type"])
        if counts_by_type.get(fact_type, 0) >= per_type:
            continue
        candidate = response_for([*selected, row])
        if len(candidate.model_dump_json()) > char_budget:
            continue
        selected.append(row)
        counts_by_type[fact_type] = counts_by_type.get(fact_type, 0) + 1

    return response_for(selected)


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
