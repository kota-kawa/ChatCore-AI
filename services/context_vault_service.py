"""Async owner-scoped personal context vault use cases."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from hashlib import sha256
from typing import Any, Awaitable, Callable, Literal, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError
from services.context_vault_embeddings import schedule_embedding
from services.db import is_retryable_db_error, session_scope
from services.embeddings import embeddings_available, generate_embedding
from services.repositories.context_fact_repository import ContextFactRepository
from services.request_models import (
    DEFAULT_CONTEXT_FACT_IMPORTANCE,
    MAX_CONTEXT_FACT_CONTENT_LENGTH,
    MAX_CONTEXT_FACT_TITLE_LENGTH,
    ContextFactSourceKind,
    ContextFactStatus,
    ContextFactType,
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
MAX_DB_WRITE_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05
ContextSearchMode = Literal["keyword", "semantic"]
_DIGEST_TYPE_ORDER = ("profile", "preference", "project", "decision", "reference")
_CURSOR_SEPARATOR = "~"
T = TypeVar("T")


class ContextSearchResult(BaseModel):
    total: int = Field(ge=0)
    facts: list[ContextFactResponse]


def _repository(session: AsyncSession) -> ContextFactRepository:
    return ContextFactRepository(session)


async def _transaction(
    session: AsyncSession | None,
    operation: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    if session is not None:
        return await operation(session)
    for attempt in range(MAX_DB_WRITE_ATTEMPTS):
        try:
            async with session_scope() as db:
                async with db.begin():
                    return await operation(db)
        except ApiServiceError:
            raise
        except SQLAlchemyError as exc:
            if attempt + 1 >= MAX_DB_WRITE_ATTEMPTS or not is_retryable_db_error(exc):
                raise
            await asyncio.sleep(DB_RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise RuntimeError("Context transaction retry loop exhausted.")


def _to_response(fact: dict[str, Any]) -> ContextFactResponse:
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
    return f"{updated_at}{_CURSOR_SEPARATOR}{int(fact['id'])}" if updated_at else None


def _decode_cursor(cursor: str | None) -> tuple[datetime, int] | None:
    if not cursor:
        return None
    raw, separator, id_part = cursor.rpartition(_CURSOR_SEPARATOR)
    if not separator or not raw or not id_part:
        raise ApiServiceError("ページングカーソルが不正です。", 400, status="fail")
    try:
        return datetime.fromisoformat(raw), int(id_part)
    except (TypeError, ValueError) as exc:
        raise ApiServiceError("ページングカーソルが不正です。", 400, status="fail") from exc


def _safe_list_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_CONTEXT_LIST_LIMIT))


def _safe_search_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_CONTEXT_SEARCH_LIMIT))


async def list_facts(
    user_id: int,
    *,
    fact_type: ContextFactType | None = None,
    status: ContextFactStatus = "active",
    limit: int = DEFAULT_CONTEXT_LIST_LIMIT,
    cursor: str | None = None,
    session: AsyncSession | None = None,
) -> ContextFactListResponse:
    async def operation(db: AsyncSession) -> ContextFactListResponse:
        safe_limit = _safe_list_limit(limit)
        decoded = _decode_cursor(cursor)
        rows = await _repository(db).list_facts(
            user_id,
            fact_type=fact_type,
            status=status,
            limit=safe_limit + 1,
            before_updated_at=decoded[0] if decoded else None,
            before_id=decoded[1] if decoded else None,
        )
        next_cursor = None
        if len(rows) > safe_limit:
            next_cursor = _encode_cursor(rows[safe_limit - 1])
            rows = rows[:safe_limit]
        return ContextFactListResponse(
            facts=[_to_response(row) for row in rows],
            total_active=await _repository(db).count_active(user_id),
            next_cursor=next_cursor,
        )

    return await _transaction(session, operation)


async def get_fact(
    user_id: int,
    fact_id: int,
    *,
    session: AsyncSession | None = None,
) -> ContextFactResponse:
    return _to_response(await _transaction(session, lambda db: _repository(db).get_fact(user_id, fact_id)))


async def create_fact(
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
    session: AsyncSession | None = None,
) -> ContextFactResponse:
    normalized_title = title.strip()[:MAX_CONTEXT_FACT_TITLE_LENGTH]
    normalized_content = content.strip()[:MAX_CONTEXT_FACT_CONTENT_LENGTH]
    normalized_importance = max(0, min(int(importance), 100))
    normalized_source_ref = source_ref.strip()[:500] if source_ref else None
    key_hash = None
    payload_hash = None
    if idempotency_key is not None:
        key_hash = sha256(
            f"{user_id}\0{source_kind}\0{source_client_id or ''}\0{idempotency_key}".encode()
        ).hexdigest()
        canonical = json.dumps(
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
        payload_hash = sha256(canonical.encode("utf-8")).hexdigest()

    fact = await _transaction(
        session,
        lambda db: _repository(db).create_fact(
            user_id,
            fact_type=fact_type,
            title=normalized_title,
            content=normalized_content,
            source_kind=source_kind,
            source_ref=normalized_source_ref,
            source_client_id=source_client_id,
            importance=normalized_importance,
            idempotency_key_hash=key_hash,
            idempotency_payload_hash=payload_hash,
        ),
    )
    if session is None and not fact.get("_idempotent_replay"):
        schedule_embedding(
            int(fact["id"]),
            str(fact["fact_type"]),
            str(fact["title"]),
            str(fact["content"]),
            int(fact["revision"]),
        )
    return _to_response(fact)


async def update_fact(
    user_id: int,
    fact_id: int,
    *,
    expected_revision: int,
    title: str | None = None,
    content: str | None = None,
    fact_type: ContextFactType | None = None,
    status: ContextFactStatus | None = None,
    importance: int | None = None,
    session: AsyncSession | None = None,
) -> ContextFactResponse:
    fact = await _transaction(
        session,
        lambda db: _repository(db).update_fact(
            user_id,
            fact_id,
            expected_revision=expected_revision,
            title=title.strip()[:MAX_CONTEXT_FACT_TITLE_LENGTH] if title is not None else None,
            content=content.strip()[:MAX_CONTEXT_FACT_CONTENT_LENGTH] if content is not None else None,
            fact_type=fact_type,
            status=status,
            importance=max(0, min(int(importance), 100)) if importance is not None else None,
        ),
    )
    if session is None and str(fact.get("status")) == "active":
        schedule_embedding(
            int(fact["id"]),
            str(fact["fact_type"]),
            str(fact["title"]),
            str(fact["content"]),
            int(fact["revision"]),
        )
    return _to_response(fact)


async def deprecate_fact(
    user_id: int,
    fact_id: int,
    *,
    expected_revision: int,
    session: AsyncSession | None = None,
) -> ContextFactResponse:
    return await update_fact(
        user_id,
        fact_id,
        expected_revision=expected_revision,
        status="deprecated",
        session=session,
    )


async def build_digest(
    user_id: int,
    *,
    limit_per_type: int = DEFAULT_DIGEST_LIMIT_PER_TYPE,
    max_chars: int = DEFAULT_DIGEST_MAX_CHARS,
    session: AsyncSession | None = None,
) -> ContextDigestResponse:
    async def operation(db: AsyncSession) -> ContextDigestResponse:
        per_type = max(1, min(int(limit_per_type), MAX_DIGEST_LIMIT_PER_TYPE))
        char_budget = max(MIN_DIGEST_MAX_CHARS, min(int(max_chars), MAX_DIGEST_MAX_CHARS))
        rows = await _repository(db).list_active_for_digest(user_id)
        total_active = len(rows)
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

    return await _transaction(session, operation)


async def search_facts(
    user_id: int,
    query: str,
    *,
    mode: ContextSearchMode = "keyword",
    limit: int = DEFAULT_CONTEXT_SEARCH_LIMIT,
    session: AsyncSession | None = None,
) -> ContextSearchResult:
    normalized_query = query.strip()
    if not normalized_query:
        raise ApiServiceError("検索語を指定してください。", 400, status="fail")

    async def operation(db: AsyncSession) -> ContextSearchResult:
        repo = _repository(db)
        rows: list[dict[str, Any]] = []
        if mode == "semantic" and embeddings_available():
            try:
                embedding = await asyncio.to_thread(generate_embedding, normalized_query)
            except Exception:
                embedding = None
                logger.warning("Failed to generate a context search embedding; using keyword search.", exc_info=True)
            if embedding:
                rows = await repo.semantic_search(
                    user_id, embedding, limit=_safe_search_limit(limit), status="active"
                )
        if not rows:
            rows = await repo.text_search(
                user_id,
                normalized_query,
                limit=_safe_search_limit(limit),
                status="active",
            )
        return ContextSearchResult(total=len(rows), facts=[_to_response(row) for row in rows])

    return await _transaction(session, operation)
