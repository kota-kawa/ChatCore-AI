"""LLM が会話から自動抽出した記憶（個人コンテキストの事実）のユースケース。

抽出結果の保存（未確認の事実として直接保存し、上限のときは手を入れていない自動保存の事実を入れ替える）と、
抽出機能の ON/OFF 設定を扱う。

Use cases for memory (personal-context facts) that the LLM extracts from conversations.
Covers storing extraction results (saved directly as unconfirmed facts, replacing an untouched auto-saved fact at the
cap) and the extraction setting.
"""

from __future__ import annotations

import asyncio
import json
import unicodedata
from collections.abc import Awaitable, Callable
from hashlib import sha256
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError
from services.context_vault_embeddings import schedule_embedding
from services.db import is_retryable_db_error, session_scope
from services.repositories.context_fact_candidate_repository import ContextFactCandidateRepository
from services.request_models import (
    DEFAULT_CONTEXT_FACT_IMPORTANCE,
    MAX_CONTEXT_FACT_CONTENT_LENGTH,
    MAX_CONTEXT_FACT_EVIDENCE_LENGTH,
    MAX_CONTEXT_FACT_TITLE_LENGTH,
    ContextFactType,
)
from services.response_models import ContextExtractionSettingsResponse

MAX_DB_WRITE_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05
T = TypeVar("T")


# LLM が返した候補 1 件の検証モデル。不正な候補は呼び出し側で捨てる（余分なキーは無視）。
# Validation model for one LLM-returned candidate; invalid ones are dropped by the caller (extra keys ignored).
class _ExtractedCandidateInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    fact_type: ContextFactType
    title: str = Field(min_length=1, max_length=MAX_CONTEXT_FACT_TITLE_LENGTH)
    content: str = Field(min_length=1, max_length=MAX_CONTEXT_FACT_CONTENT_LENGTH)
    # 本人発話の引用。出典として残すため、長さの超過は候補を落とさず保存時に切り詰める。
    # The owner's quoted words kept as the source; an overlong quote is truncated at storage, not a reason to drop the candidate.
    evidence: str = ""
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
    """記憶の自動抽出のユースケースを明示的なトランザクションで実行する。session を渡された場合は呼び出し側に任せ、
    渡されない場合は一時的な DB エラーに限り最大 MAX_DB_WRITE_ATTEMPTS 回までバックオフ付きで再試行する。

    Run one extraction use case in an explicit transaction. A caller-supplied session is used as is;
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
    raise RuntimeError("Context extraction transaction retry loop exhausted.")


# 正規化（NFKC・空白圧縮・大文字小文字無視）した種別・題名・本文のハッシュ。本人が却下した候補と同じ内容を再び保存しないために使う。
# Hash of the normalized type/title/content (NFKC, collapsed whitespace, casefolded), used to avoid saving content the owner rejected again.
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
    room_id: str | None = None,
    user_message_id: int | None = None,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    """LLM が抽出した内容を検証し、抽出を許可しているユーザーの記憶として重複なく保存する。
    本人未確認の事実として直接保存し（保存後に埋め込みを予約する）、有効件数が上限のときは、自動保存のまま本人が
    手を入れていない事実を無効化して入れ替える（入れ替えられる事実が無ければ保存しない）。検証に通らない候補は
    黙って捨てる。保存した事実の一覧を返す。
    room_id があれば、候補の evidence（本人発話の引用）を出典として残す（user_message_id は引用元の発話）。
    session を渡した場合、埋め込みの予約はコミット後に呼び出し側が行う。

    Validate LLM-extracted content and store it as unique memory for an owner who has extraction enabled.
    It is saved directly as unconfirmed facts (embeddings are scheduled after the commit); at the active-fact cap an
    auto-saved fact the owner never touched is deprecated to make room, and nothing is saved when none can be replaced.
    Invalid candidates are silently skipped. Returns the facts saved.
    With a room_id, each candidate's evidence (the owner's quoted words) is kept as a source (user_message_id is
    the message it came from). With a caller-supplied session, the caller schedules embeddings after its own commit.
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
                "evidence": candidate.evidence[:MAX_CONTEXT_FACT_EVIDENCE_LENGTH].strip(),
                "importance": candidate.importance,
                "confidence": candidate.confidence,
                "fingerprint": _fingerprint(candidate),
            }
        )
    if not prepared:
        return []

    async def operation(db: AsyncSession) -> list[dict[str, Any]]:
        repo = _repository(db)
        if not await repo.get_extraction_settings(user_id):
            return []
        return await repo.store_extracted(user_id, prepared, room_id=room_id, user_message_id=user_message_id)

    saved_facts = await _transaction(session, operation)
    if session is None:
        for fact in saved_facts:
            schedule_embedding(
                int(fact["id"]),
                str(fact["fact_type"]),
                str(fact["title"]),
                str(fact["content"]),
                int(fact["revision"]),
            )
    return saved_facts


async def is_context_extraction_enabled(
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> bool:
    return await _transaction(
        session,
        lambda db: _repository(db).get_extraction_settings(user_id),
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
