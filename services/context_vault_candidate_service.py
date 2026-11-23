"""LLM が会話から自動抽出した記憶（個人コンテキストの事実）のユースケース。

抽出結果の保存（未確認の事実として直接保存し、上限のときは手を入れていない自動保存の事実を入れ替える）と、
保存前の既存の記憶との照合（食い違う古い記憶の置き換え・言い換えの再言及）、抽出機能の ON/OFF 設定を扱う。

Use cases for memory (personal-context facts) that the LLM extracts from conversations.
Covers storing extraction results (saved directly as unconfirmed facts, replacing an untouched auto-saved fact at the
cap), reconciling them with existing memory before storage (replacing a contradicted old memory, re-mentioning a
reworded one) and the extraction setting.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from hashlib import sha256
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError
from services.context_vault_embeddings import build_context_fact_embedding_text, schedule_embedding
from services.context_vault_extraction import normalize_for_comparison
from services.context_vault_reconcile import (
    CONTEXT_RECONCILE_MODEL,
    RECONCILE_MAX_DISTANCE,
    RECONCILE_NEIGHBOR_LIMIT,
    CandidatePlan,
    ReconcileResolution,
    RelatedFact,
    build_reconcile_messages,
    nearby_for_candidate,
    resolve_reconcile_decisions,
)
from services.db import is_retryable_db_error, session_scope
from services.embeddings import embeddings_available, generate_embedding
from services.llm import get_llm_json_response
from services.repositories.context_fact_candidate_repository import ContextFactCandidateRepository
from services.repositories.context_fact_repository import ContextFactRepository
from services.request_models import (
    DEFAULT_CONTEXT_FACT_IMPORTANCE,
    MAX_CONTEXT_FACT_CONTENT_LENGTH,
    MAX_CONTEXT_FACT_EVIDENCE_LENGTH,
    MAX_CONTEXT_FACT_TITLE_LENGTH,
    ContextFactType,
)
from services.response_models import ContextExtractionSettingsResponse

logger = logging.getLogger(__name__)

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
    canonical = json.dumps(
        {
            "content": normalize_for_comparison(candidate.content),
            "fact_type": candidate.fact_type,
            "title": normalize_for_comparison(candidate.title),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


# 日本語: 保存の前に行う、既存の記憶との照合。重複判定(BM25)を通った候補と、BM25 の最良一致が有効な記憶だった候補(語の重なりで重複と
# みなされても、食い違い・追加の細部かもしれないため、再言及と決める前に判定させる)を対象にする。対象の候補は埋め込みが使えれば埋め込み、
# 近い記憶(BM25 で一致した有効な記憶は必ず、埋め込みで近い記憶があれば合わせて最大 5 件)が 1 件でもあるときだけ LLM で追加・更新・
# 再言及を判定する。BM25 の最良一致が本人の無効化した記憶・却下済みの候補・同じバッチの別候補の候補は対象にしない(従来どおり何も
# 保存しない)。advisory lock も DB のトランザクションも、埋め込みと LLM の呼び出しをまたいで持たない(短い読み取りが 2 回あるだけ)。
# 保存はこの後、ロックの中で対象の状態を確かめ直して適用する。どの段階が失敗しても保存は止めず、その段階までに作れた埋め込みと BM25 の
# 一致だけを残して、判定の無い候補は従来どおり(有効な記憶に一致した候補は再言及、それ以外は新しい記憶)に倒す(ログには記憶の文面も
# 応答も出さず、例外の種類だけを残す)。
# English: Reconciliation with existing memory, run before storage. It covers candidates that passed the BM25 duplicate check and
# candidates whose BM25 best match was an active memory (word overlap can call them duplicates although they are a contradiction or
# an added detail, so they are judged before being settled as a re-mention). Targeted candidates are embedded when embeddings are
# available, and the LLM decides add / update / re-mention only when there is any nearby memory (the active memory BM25 matched,
# always, plus up to 5 in total found by embedding). Candidates whose BM25 best match was a memory the owner deactivated, a rejected
# candidate or another candidate of the same batch are not targeted (nothing is saved, as before). Neither the advisory lock nor a DB
# transaction is held across the embedding or the LLM call (there are just two short reads); storage applies the result afterwards
# inside the lock, re-checking the target's state. A failure at any stage never stops storage: only the embeddings and BM25 matches
# gathered so far are kept, and a candidate without a decision falls back to the earlier behavior (a re-mention when it matched an
# active memory, otherwise a new memory). The log carries neither memory text nor the response, only the error type.
async def _plan_reconciliation(user_id: int, prepared: list[dict[str, Any]]) -> dict[int, CandidatePlan]:
    matched_fact_ids: dict[int, int] = {}
    embeddings: dict[int, list[float]] = {}
    resolutions: dict[int, ReconcileResolution] = {}
    try:
        unique_indexes = await _classify_candidates(user_id, prepared, matched_fact_ids)
        await _embed_candidates(prepared, sorted(set(unique_indexes) | set(matched_fact_ids)), embeddings)
        resolutions = await _resolve_against_nearby_memory(user_id, prepared, embeddings, matched_fact_ids)
    except Exception as exc:
        logger.warning(
            "Memory reconciliation failed; storing the candidates without it.",
            extra={"user_id": user_id, "error_type": type(exc).__name__},
        )
    return {
        index: CandidatePlan(
            embedding=embeddings.get(index),
            resolution=resolutions.get(index),
            matched_fact_id=matched_fact_ids.get(index),
        )
        for index in set(embeddings) | set(matched_fact_ids)
    }


# 日本語: 抽出の設定が有効なら、BM25 の重複判定で既存の内容と重複しなかった候補の添字を返し、最良一致が有効な記憶だった候補は、その
# 記憶の id を matched_fact_ids(候補の添字から)へ入れる。最良一致がそれ以外(本人の無効化した記憶・却下済みの候補・同じバッチの候補)の候補は
# どちらにも入れない。設定が無効なら空。ロックを取らない短い読み取り。
# English: With extraction enabled, returns the indexes of candidates the BM25 duplicate check found unique, and records into
# matched_fact_ids (by candidate index) the id of the active memory for candidates whose best match was one. Candidates whose best
# match was anything else (a memory the owner deactivated, a rejected candidate, a same-batch candidate) go into neither. Nothing
# when the setting is off. A short read without the lock.
async def _classify_candidates(user_id: int, prepared: list[dict[str, Any]], matched_fact_ids: dict[int, int]) -> list[int]:
    async def operation(db: AsyncSession) -> tuple[list[int], dict[int, int]]:
        repo = _repository(db)
        if not await repo.get_extraction_settings(user_id):
            return [], {}
        matches = await repo.find_duplicate_matches(user_id, prepared)
        unique = [index for index, match in enumerate(matches) if match is None]
        active = {
            index: int(match["fact_id"])
            for index, match in enumerate(matches)
            if match is not None and match.get("fact_status") == "active"
        }
        return unique, active

    unique_indexes, active_matches = await _transaction(None, operation)
    matched_fact_ids.update(active_matches)
    return unique_indexes


# 日本語: 埋め込みの文面は schedule_embedding と同じ build_context_fact_embedding_text で、保存する事実の種類・題名・本文そのものから作る。
# そのため、ここで作った埋め込みを保存にそのまま使っても、保存後に作り直す埋め込みと同じ文面になる。埋め込みが使えない・失敗した候補は
# 含めない(保存後の予約に任せる)。作れた分は途中で失敗しても捨てないよう、呼び出し側の embeddings へその都度入れる。
# English: The embedding text comes from the same build_context_fact_embedding_text as schedule_embedding, over the very type, title
# and content that will be stored, so reusing this embedding at storage matches what re-embedding after the save would produce.
# Candidates whose embedding is unavailable or failed are left out (the post-save scheduling covers them). Each embedding is put
# into the caller's embeddings as soon as it exists, so a later failure does not discard the ones already made.
async def _embed_candidates(prepared: list[dict[str, Any]], indexes: list[int], embeddings: dict[int, list[float]]) -> None:
    if not indexes or not embeddings_available():
        return
    for index in indexes:
        candidate = prepared[index]
        text = build_context_fact_embedding_text(candidate["fact_type"], candidate["title"], candidate["content"])
        embedding = await asyncio.to_thread(generate_embedding, text)
        if embedding:
            embeddings[index] = embedding


# 日本語: 対象の候補ごとに近い記憶を読み(短い読み取り)、1 件でもあるときだけ LLM を呼んで判定を適用した結果を返す。近い記憶は、BM25 で
# 一致した有効な記憶(埋め込みの有無・距離に関係なく先頭)と、埋め込みで近い記憶(埋め込みがある候補だけ)。BM25 の一致も埋め込みも無ければ
# 何も読まず、近い記憶が 1 件も無ければ LLM を呼ばず、空を返す(判定の無い候補は従来どおりに保存される)。
# English: Reads the nearby memories per targeted candidate (a short read) and, only when there is any, calls the LLM and returns the
# decisions after the rules are applied. Nearby memories are the active memory BM25 matched (first, regardless of embedding or
# distance) and the memories close by embedding (only for candidates that have one). With neither a BM25 match nor an embedding
# nothing is read, and with no nearby memory the LLM is not called and the result is empty (candidates without a decision are stored
# as before).
async def _resolve_against_nearby_memory(
    user_id: int,
    prepared: list[dict[str, Any]],
    embeddings: dict[int, list[float]],
    matched_fact_ids: dict[int, int],
) -> dict[int, ReconcileResolution]:
    if not embeddings and not matched_fact_ids:
        return {}

    async def read_nearby(db: AsyncSession) -> dict[int, list[RelatedFact]]:
        facts = ContextFactRepository(db)
        matched_facts: dict[int, RelatedFact] = {}
        if matched_fact_ids:
            rows = await facts.get_reconcile_facts(user_id, sorted(set(matched_fact_ids.values())))
            matched_facts = {int(row["id"]): _related_fact(row) for row in rows}
        related: dict[int, list[RelatedFact]] = {}
        for index in sorted(set(embeddings) | set(matched_fact_ids)):
            neighbors: list[RelatedFact] = []
            if index in embeddings:
                rows = await facts.find_reconcile_neighbors(
                    user_id,
                    embeddings[index],
                    limit=RECONCILE_NEIGHBOR_LIMIT,
                    max_distance=RECONCILE_MAX_DISTANCE,
                )
                neighbors = [_related_fact(row) for row in rows]
            nearby = nearby_for_candidate(matched_facts.get(matched_fact_ids.get(index, 0)), neighbors)
            if nearby:
                related[index] = nearby
        return related

    related_by_candidate = await _transaction(None, read_nearby)
    if not related_by_candidate:
        return {}
    messages = build_reconcile_messages(prepared, related_by_candidate)
    raw_response = await asyncio.to_thread(get_llm_json_response, messages, CONTEXT_RECONCILE_MODEL)
    return resolve_reconcile_decisions(raw_response, related_by_candidate)


def _related_fact(row: dict[str, Any]) -> RelatedFact:
    last_mentioned = row.get("last_mentioned")
    return RelatedFact(
        fact_id=int(row["id"]),
        revision=int(row["revision"]),
        fact_type=str(row["fact_type"]),
        title=str(row["title"] or ""),
        content=str(row["content"] or ""),
        status="active" if row["status"] == "active" else "deprecated",
        last_mentioned=last_mentioned.date() if last_mentioned is not None else None,
    )


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
    session を渡した場合、埋め込みの予約はコミット後に呼び出し側が行い、既存の記憶との照合(埋め込み・LLM)は行わない
    (呼び出し側のトランザクションを LLM の呼び出しをまたいで開いたままにしないため)。

    保存の前に、重複しなかった候補と、BM25 で有効な記憶と重複とみなされた候補を既存の記憶と照合する(_plan_reconciliation)。
    近い記憶(BM25 で一致した有効な記憶、埋め込みで近い記憶)があれば、同じ事柄で古くなった記憶を新しい記憶で置き換え
    (古い記憶は消さずに無効化)、言い換えなら新しい記憶を作らない。照合が何もしなければ従来どおり(有効な記憶との重複は再言及)。照合で作った埋め込みは保存にそのまま
    使い、保存後の予約は埋め込みが保存されていない事実にだけ行う。

    Validate LLM-extracted content and store it as unique memory for an owner who has extraction enabled.
    It is saved directly as unconfirmed facts (embeddings are scheduled after the commit); at the active-fact cap an
    auto-saved fact the owner never touched is deprecated to make room, and nothing is saved when none can be replaced.
    Invalid candidates are silently skipped. Returns the facts saved.
    With a room_id, each candidate's evidence (the owner's quoted words) is kept as a source (user_message_id is
    the message it came from). With a caller-supplied session, the caller schedules embeddings after its own commit and
    reconciliation with existing memory (embedding, LLM) is skipped, so the caller's transaction is never held open across
    an LLM call.

    Before storage, candidates that were not duplicates, and those BM25 called duplicates of an active memory, are reconciled
    with existing memory (_plan_reconciliation). With a nearby memory (the active memory BM25 matched, memories close by
    embedding), a newer memory replaces an outdated one about the same matter (the old one is deprecated, not deleted), and a
    reworded one creates no new memory. When reconciliation does nothing the earlier behavior holds (a duplicate of an active
    memory is a re-mention). The embedding made for reconciling is stored as is, and the
    post-save scheduling covers only facts saved without an embedding.
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

    plans = await _plan_reconciliation(user_id, prepared) if session is None else None

    async def operation(db: AsyncSession) -> list[dict[str, Any]]:
        repo = _repository(db)
        if not await repo.get_extraction_settings(user_id):
            return []
        return await repo.store_extracted(
            user_id,
            prepared,
            room_id=room_id,
            user_message_id=user_message_id,
            plans=plans,
        )

    saved_facts = await _transaction(session, operation)
    if session is None:
        for fact in saved_facts:
            if fact.get("embedding_status") == "ready":
                continue
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
