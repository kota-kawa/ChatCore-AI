"""Review queue operations for automatically extracted personal context facts."""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from services.api_errors import ApiServiceError
from services.context_vault_embeddings import schedule_embedding
from services.error_messages import ERROR_CONTEXT_FACT_CANDIDATE_CURSOR_INVALID
from services.repositories.context_fact_candidate_repository import (
    ContextFactCandidateRepository,
)
from services.request_models import (
    DEFAULT_CONTEXT_FACT_IMPORTANCE,
    MAX_CONTEXT_FACT_CONTENT_LENGTH,
    MAX_CONTEXT_FACT_TITLE_LENGTH,
    ContextFactCandidateStatus,
    ContextFactType,
)
from services.response_models import (
    ContextExtractionSettingsResponse,
    ContextFactCandidateApprovalResponse,
    ContextFactCandidateListResponse,
    ContextFactCandidateResponse,
    ContextFactResponse,
)

DEFAULT_CONTEXT_CANDIDATE_LIST_LIMIT = 20
MAX_CONTEXT_CANDIDATE_LIST_LIMIT = 50
_CURSOR_SEPARATOR = "~"


class _ExtractedCandidateInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    fact_type: ContextFactType
    title: str = Field(min_length=1, max_length=MAX_CONTEXT_FACT_TITLE_LENGTH)
    content: str = Field(min_length=1, max_length=MAX_CONTEXT_FACT_CONTENT_LENGTH)
    importance: int = Field(default=DEFAULT_CONTEXT_FACT_IMPORTANCE, ge=0, le=100)
    confidence: float = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def _require_non_blank_text(self) -> "_ExtractedCandidateInput":
        if not self.title.strip() or not self.content.strip():
            raise ValueError("Extracted candidate text must not be blank.")
        return self


def _repository() -> ContextFactCandidateRepository:
    return ContextFactCandidateRepository()


def _to_candidate_response(candidate: dict[str, Any]) -> ContextFactCandidateResponse:
    """Allowlist candidate fields; never expose owner, fingerprint, or promoted id."""
    return ContextFactCandidateResponse(
        id=int(candidate["id"]),
        fact_type=str(candidate["fact_type"]),
        title=str(candidate.get("title") or ""),
        content=str(candidate.get("content") or ""),
        source_kind=str(candidate.get("source_kind") or "chat"),
        source_ref=(
            str(candidate["source_ref"])
            if candidate.get("source_ref") is not None
            else None
        ),
        importance=max(0, min(int(candidate.get("importance", 50)), 100)),
        confidence=max(0, min(float(candidate.get("confidence", 0)), 1)),
        status=str(candidate.get("status") or "pending"),
        revision=max(int(candidate.get("revision") or 1), 1),
        created_at=candidate.get("created_at"),
        updated_at=candidate.get("updated_at"),
    )


def _to_fact_response(fact: dict[str, Any]) -> ContextFactResponse:
    return ContextFactResponse(
        id=int(fact["id"]),
        fact_type=str(fact["fact_type"]),
        title=str(fact.get("title") or ""),
        content=str(fact.get("content") or ""),
        status=str(fact.get("status") or "active"),
        revision=max(int(fact.get("revision") or 1), 1),
        source_kind=str(fact.get("source_kind") or "chat"),
        importance=max(0, min(int(fact.get("importance", 50)), 100)),
        created_at=fact.get("created_at"),
        updated_at=fact.get("updated_at"),
    )


def _fingerprint(candidate: _ExtractedCandidateInput) -> str:
    def normalized(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()

    canonical = json.dumps(
        {
            "content": normalized(candidate.content),
            "fact_type": candidate.fact_type,
            "title": normalized(candidate.title),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def store_extracted_candidates(
    user_id: int,
    *,
    candidates: list[dict[str, Any]],
    source_ref: str,
) -> int:
    """Validate and enqueue unique LLM-extracted facts for an opted-in owner."""
    repo = _repository()
    if not repo.get_extraction_settings(user_id):
        return 0

    normalized_source_ref = source_ref.strip()[:500] or None
    prepared: list[dict[str, Any]] = []
    for raw_candidate in candidates:
        if not isinstance(raw_candidate, dict):
            continue
        try:
            candidate = _ExtractedCandidateInput.model_validate(raw_candidate)
        except ValidationError:
            continue
        prepared.append(
            {
                "fact_type": candidate.fact_type,
                "title": candidate.title.strip(),
                "content": candidate.content.strip(),
                "source_kind": "chat",
                "source_ref": normalized_source_ref,
                "importance": candidate.importance,
                "confidence": candidate.confidence,
                "fingerprint": _fingerprint(candidate),
            }
        )
    if not prepared:
        return 0
    return repo.store_candidates(user_id, prepared)


def _decode_cursor(cursor: str | None) -> tuple[datetime, int] | None:
    if not cursor:
        return None
    raw, separator, id_part = cursor.rpartition(_CURSOR_SEPARATOR)
    if not separator or not raw or not id_part:
        raise ApiServiceError(
            ERROR_CONTEXT_FACT_CANDIDATE_CURSOR_INVALID,
            400,
            status="fail",
        )
    try:
        return datetime.fromisoformat(raw), int(id_part)
    except (TypeError, ValueError) as exc:
        raise ApiServiceError(
            ERROR_CONTEXT_FACT_CANDIDATE_CURSOR_INVALID,
            400,
            status="fail",
        ) from exc


def list_candidates(
    user_id: int,
    *,
    status: ContextFactCandidateStatus = "pending",
    limit: int = DEFAULT_CONTEXT_CANDIDATE_LIST_LIMIT,
    cursor: str | None = None,
) -> ContextFactCandidateListResponse:
    repo = _repository()
    safe_limit = max(1, min(int(limit), MAX_CONTEXT_CANDIDATE_LIST_LIMIT))
    decoded = _decode_cursor(cursor)
    rows = repo.list_candidates(
        user_id,
        status=status,
        limit=safe_limit + 1,
        before_created_at=decoded[0] if decoded else None,
        before_id=decoded[1] if decoded else None,
    )
    next_cursor: str | None = None
    if len(rows) > safe_limit:
        last = rows[safe_limit - 1]
        if last.get("created_at"):
            next_cursor = f"{last['created_at']}{_CURSOR_SEPARATOR}{int(last['id'])}"
        rows = rows[:safe_limit]
    return ContextFactCandidateListResponse(
        candidates=[_to_candidate_response(row) for row in rows],
        next_cursor=next_cursor,
        total_pending=repo.count_pending(user_id),
    )


def approve_candidate(
    user_id: int,
    candidate_id: int,
    *,
    expected_revision: int,
    fact_type: ContextFactType | None = None,
    title: str | None = None,
    content: str | None = None,
    importance: int | None = None,
) -> ContextFactCandidateApprovalResponse:
    candidate, fact = _repository().approve_candidate(
        user_id,
        candidate_id,
        expected_revision=expected_revision,
        fact_type=fact_type,
        title=title.strip()[:MAX_CONTEXT_FACT_TITLE_LENGTH] if title is not None else None,
        content=(
            content.strip()[:MAX_CONTEXT_FACT_CONTENT_LENGTH]
            if content is not None
            else None
        ),
        importance=(max(0, min(int(importance), 100)) if importance is not None else None),
    )
    schedule_embedding(
        int(fact["id"]),
        str(fact["fact_type"]),
        str(fact["title"]),
        str(fact["content"]),
        int(fact["revision"]),
    )
    return ContextFactCandidateApprovalResponse(
        candidate=_to_candidate_response(candidate),
        fact=_to_fact_response(fact),
    )


def reject_candidate(
    user_id: int,
    candidate_id: int,
    *,
    expected_revision: int,
) -> ContextFactCandidateResponse:
    candidate = _repository().reject_candidate(
        user_id,
        candidate_id,
        expected_revision=expected_revision,
    )
    return _to_candidate_response(candidate)


def is_context_extraction_enabled(user_id: int) -> bool:
    return _repository().get_extraction_settings(user_id)


def should_extract_context(user_id: int) -> bool:
    return _repository().should_extract_context(user_id)


def get_extraction_settings(user_id: int) -> ContextExtractionSettingsResponse:
    return ContextExtractionSettingsResponse(enabled=is_context_extraction_enabled(user_id))


def update_extraction_settings(
    user_id: int,
    enabled: bool,
) -> ContextExtractionSettingsResponse:
    updated = _repository().update_extraction_settings(user_id, enabled)
    return ContextExtractionSettingsResponse(enabled=updated)
