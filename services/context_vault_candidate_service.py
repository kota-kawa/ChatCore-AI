"""LLM が会話から自動抽出した記憶（個人コンテキストの事実）のユースケース。

抽出結果の保存（空きがあれば未確認の事実として直接保存し、上限で入らない分は承認待ち候補へ）、
候補の一覧・承認・却下、抽出機能の ON/OFF 設定を扱う。

Use cases for memory (personal-context facts) that the LLM extracts from conversations.
Covers storing extraction results (saved directly as unconfirmed facts while there is room, the rest queued
as pending candidates), listing/approving/rejecting candidates, and the extraction setting.
"""

from __future__ import annotations

import asyncio
import json
import unicodedata
from collections.abc import Awaitable, Callable
from datetime import datetime
from hashlib import sha256
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError
from services.context_vault_embeddings import schedule_embedding
from services.db import is_retryable_db_error, session_scope
from services.error_messages import ERROR_CONTEXT_FACT_CANDIDATE_CURSOR_INVALID
from services.repositories.context_fact_candidate_repository import (
    ContextFactCandidateRepository,
    ExtractedStoreResult,
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
MAX_DB_WRITE_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05
_CURSOR_SEPARATOR = "~"
T = TypeVar("T")


# LLM が返した候補 1 件の検証モデル。不正な候補は呼び出し側で捨てる（余分なキーは無視）。
# Validation model for one LLM-returned candidate; invalid ones are dropped by the caller (extra keys ignored).
class _ExtractedCandidateInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    fact_type: ContextFactType
    title: str = Field(min_length=1, max_length=MAX_CONTEXT_FACT_TITLE_LENGTH)
    content: str = Field(min_length=1, max_length=MAX_CONTEXT_FACT_CONTENT_LENGTH)
    importance: int = Field(default=DEFAULT_CONTEXT_FACT_IMPORTANCE, ge=0, le=100)
    confidence: float = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def _require_non_blank_text(self) -> _ExtractedCandidateInput:
        if not self.title.strip() or not self.content.strip():
            raise ValueError("Extracted candidate text must not be blank.")
        return self


def _repository(session: AsyncSession) -> ContextFactCandidateRepository:
    return ContextFactCandidateRepository(session)


async def _transaction(
    session: AsyncSession | None,
    operation: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    """候補ユースケースを明示的なトランザクションで実行する。session を渡された場合は呼び出し側に任せ、
    渡されない場合は一時的な DB エラーに限り最大 MAX_DB_WRITE_ATTEMPTS 回までバックオフ付きで再試行する。

    Run one candidate use case in an explicit transaction. A caller-supplied session is used as is;
    otherwise retryable DB errors are retried with backoff up to MAX_DB_WRITE_ATTEMPTS times.
    """
    if session is not None:
        return await operation(session)

    for attempt in range(MAX_DB_WRITE_ATTEMPTS):
        try:
            async with session_scope() as db, db.begin():
                return await operation(db)
        except ApiServiceError:
            raise
        except SQLAlchemyError as exc:
            if attempt + 1 >= MAX_DB_WRITE_ATTEMPTS or not is_retryable_db_error(exc):
                raise
            await asyncio.sleep(DB_RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise RuntimeError("Context candidate transaction retry loop exhausted.")


def _to_candidate_response(candidate: dict[str, Any]) -> ContextFactCandidateResponse:
    """候補のフィールドを許可リスト方式で詰め直す。所有者やフィンガープリントは返さない。

    Allowlist candidate fields; never expose owner or fingerprint data.
    """
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
        confidence=fact.get("confidence"),
        last_confirmed_at=fact.get("last_confirmed_at"),
        created_at=fact.get("created_at"),
        updated_at=fact.get("updated_at"),
    )


# 正規化（NFKC・空白圧縮・大文字小文字無視）した種別・題名・本文のハッシュ。表記ゆれによる重複候補の抑止に使う。
# Hash of the normalized type/title/content (NFKC, collapsed whitespace, casefolded), used to suppress duplicate candidates.
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


async def store_extracted_facts(
    user_id: int,
    *,
    candidates: list[dict[str, Any]],
    source_ref: str,
    session: AsyncSession | None = None,
) -> ExtractedStoreResult:
    """LLM が抽出した内容を検証し、抽出を許可しているユーザーの記憶として重複なく保存する。
    有効な事実に空きがある分は本人未確認の事実として直接保存し（保存後に埋め込みを予約する）、
    空きが無い分だけ承認待ち候補へ入れる。検証に通らない候補は黙って捨てる。
    session を渡した場合、埋め込みの予約はコミット後に呼び出し側が行う。

    Validate LLM-extracted content and store it as unique memory for an opted-in owner.
    What fits under the active-fact cap is saved directly as unconfirmed facts (embeddings are scheduled after
    the commit); only the overflow is queued as pending candidates. Invalid candidates are silently skipped.
    With a caller-supplied session, the caller schedules embeddings after its own commit.
    """
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
        return ExtractedStoreResult([], 0)

    async def operation(db: AsyncSession) -> ExtractedStoreResult:
        repo = _repository(db)
        if not await repo.get_extraction_settings(user_id):
            return ExtractedStoreResult([], 0)
        return await repo.store_extracted(user_id, prepared)

    result = await _transaction(session, operation)
    if session is None:
        for fact in result.saved_facts:
            schedule_embedding(
                int(fact["id"]),
                str(fact["fact_type"]),
                str(fact["title"]),
                str(fact["content"]),
                int(fact["revision"]),
            )
    return result


# カーソルは「作成日時~ID」形式。最後の区切りで分割するので、日時側に区切り文字が含まれても壊れない。
# The cursor is "created_at~id"; splitting on the last separator keeps it valid even if the timestamp part contained one.
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


async def list_candidates(
    user_id: int,
    *,
    status: ContextFactCandidateStatus = "pending",
    limit: int = DEFAULT_CONTEXT_CANDIDATE_LIST_LIMIT,
    cursor: str | None = None,
    session: AsyncSession | None = None,
) -> ContextFactCandidateListResponse:
    # 1 件多く取得して「次ページがあるか」を判定し、next_cursor を作る。
    # Fetch one extra row to detect whether a next page exists, then build next_cursor.
    async def operation(db: AsyncSession) -> ContextFactCandidateListResponse:
        safe_limit = max(1, min(int(limit), MAX_CONTEXT_CANDIDATE_LIST_LIMIT))
        decoded = _decode_cursor(cursor)
        repo = _repository(db)
        rows = await repo.list_candidates(
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
            total_pending=await repo.count_pending(user_id),
        )

    return await _transaction(session, operation)


async def approve_candidate(
    user_id: int,
    candidate_id: int,
    *,
    expected_revision: int,
    fact_type: ContextFactType | None = None,
    title: str | None = None,
    content: str | None = None,
    importance: int | None = None,
    session: AsyncSession | None = None,
) -> ContextFactCandidateApprovalResponse:
    async def operation(db: AsyncSession) -> tuple[dict[str, Any], dict[str, Any]]:
        return await _repository(db).approve_candidate(
            user_id,
            candidate_id,
            expected_revision=expected_revision,
            fact_type=fact_type,
            title=title.strip()[:MAX_CONTEXT_FACT_TITLE_LENGTH]
            if title is not None
            else None,
            content=content.strip()[:MAX_CONTEXT_FACT_CONTENT_LENGTH]
            if content is not None
            else None,
            importance=max(0, min(int(importance), 100))
            if importance is not None
            else None,
        )

    candidate, fact = await _transaction(session, operation)
    if session is None:
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


async def reject_candidate(
    user_id: int,
    candidate_id: int,
    *,
    expected_revision: int,
    session: AsyncSession | None = None,
) -> ContextFactCandidateResponse:
    candidate = await _transaction(
        session,
        lambda db: _repository(db).reject_candidate(
            user_id,
            candidate_id,
            expected_revision=expected_revision,
        ),
    )
    return _to_candidate_response(candidate)


async def is_context_extraction_enabled(
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> bool:
    return await _transaction(
        session,
        lambda db: _repository(db).get_extraction_settings(user_id),
    )


async def should_extract_context(
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> bool:
    return await _transaction(
        session,
        lambda db: _repository(db).should_extract_context(user_id),
    )


async def get_extraction_settings(
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> ContextExtractionSettingsResponse:
    return ContextExtractionSettingsResponse(
        enabled=await is_context_extraction_enabled(user_id, session=session),
    )


async def update_extraction_settings(
    user_id: int,
    enabled: bool,
    *,
    session: AsyncSession | None = None,
) -> ContextExtractionSettingsResponse:
    updated = await _transaction(
        session,
        lambda db: _repository(db).update_extraction_settings(user_id, enabled),
    )
    return ContextExtractionSettingsResponse(enabled=updated)
