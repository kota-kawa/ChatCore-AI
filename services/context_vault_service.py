"""個人コンテキスト（Context Vault）の事実を、所有者単位で一覧・取得・作成・更新・廃止・検索・要約（ダイジェスト）する非同期ユースケース。
永続化は ContextFactRepository に任せ、ここでは入力の正規化、冪等性キーの生成、埋め込み生成の予約を担う。

Async owner-scoped personal context vault use cases (list, get, create, update, deprecate, search, digest).
Persistence is delegated to ContextFactRepository; this module normalizes input, builds idempotency hashes
and schedules embedding generation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError
from services.context_vault_embeddings import schedule_embedding
from services.db import in_transaction_with_retry
from services.embeddings import embeddings_available, generate_embedding
from services.error_messages import ERROR_PAGING_CURSOR_INVALID, ERROR_SEARCH_QUERY_REQUIRED
from services.memory_search_ranking import MEMORY_SEARCH_RESULT_LIMIT, rank_memory_facts
from services.repositories.context_fact_curation_repository import ContextFactCurationRepository
from services.repositories.context_fact_provenance_repository import ContextFactProvenanceRepository, FactProvenance
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
    ContextFactListItemResponse,
    ContextFactListResponse,
    ContextFactResponse,
    ContextFactRevertReplacementResponse,
    ContextMemoryUseSettingsResponse,
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
_DIGEST_TYPE_ORDER = ("profile", "preference", "project", "decision", "reference")
_CURSOR_SEPARATOR = "~"


# search_facts が返す検索結果（件数と事実の一覧）。
# Search result (count and facts) returned by search_facts.
class ContextSearchResult(BaseModel):
    total: int = Field(ge=0)
    facts: list[ContextFactResponse]


def _repository(session: AsyncSession) -> ContextFactRepository:
    return ContextFactRepository(session)


# 日本語: DB の行を API 応答に詰め替える。欠けた値は既定値で補い、重要度は 0〜100 に収める。
# English: Map a DB row to the API response, filling missing values with defaults and clamping importance to 0-100.
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
        confidence=fact.get("confidence"),
        last_confirmed_at=fact.get("last_confirmed_at"),
        created_at=fact.get("created_at"),
        updated_at=fact.get("updated_at"),
    )


# 日本語: 記憶の画面の一覧用に、_to_response の内容へ無効化の理由と、出典・置き換えの関係を足す。旧バージョンのコードが復元した行は理由が
# 残るので、有効な事実には返さない。MCP・ダイジェスト・検索は _to_response のまま使い、AI に渡る内容を変えない。
# English: For the memory screen's list: _to_response plus the deprecation reason and the sources and replacement relations. An older
# code color leaves the reason when it restores a fact, so an active fact never reports one. MCP, the digest and search keep using
# _to_response, so what reaches the AI is unchanged.
def _to_list_item_response(fact: dict[str, Any], provenance: FactProvenance) -> ContextFactListItemResponse:
    base = _to_response(fact)
    return ContextFactListItemResponse(
        **base.model_dump(),
        deprecated_reason=fact.get("deprecated_reason") if base.status == "deprecated" else None,
        source_count=provenance.source_count,
        last_mentioned_at=provenance.last_mentioned_at,
        sources=provenance.sources,
        superseded_by=provenance.superseded_by,
        replaces=provenance.replaces,
    )


# 日本語: カーソルは「更新日時~ID」形式（更新日時の降順ページング用）。
# English: The cursor is "updated_at~id", used for paging in descending updated_at order.
def _encode_cursor(fact: dict[str, Any]) -> str | None:
    updated_at = fact.get("updated_at")
    return f"{updated_at}{_CURSOR_SEPARATOR}{int(fact['id'])}" if updated_at else None


def _decode_cursor(cursor: str | None) -> tuple[datetime, int] | None:
    if not cursor:
        return None
    raw, separator, id_part = cursor.rpartition(_CURSOR_SEPARATOR)
    if not separator or not raw or not id_part:
        raise ApiServiceError(ERROR_PAGING_CURSOR_INVALID, 400, status="fail")
    try:
        return datetime.fromisoformat(raw), int(id_part)
    except (TypeError, ValueError) as exc:
        raise ApiServiceError(ERROR_PAGING_CURSOR_INVALID, 400, status="fail") from exc


def _safe_list_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_CONTEXT_LIST_LIMIT))


def _safe_search_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_CONTEXT_SEARCH_LIMIT))


async def list_facts(
    user_id: int,
    *,
    fact_type: ContextFactType | None = None,
    status: ContextFactStatus = "active",
    query: str | None = None,
    limit: int = DEFAULT_CONTEXT_LIST_LIMIT,
    cursor: str | None = None,
    session: AsyncSession | None = None,
) -> ContextFactListResponse:
    # 1 件多く取得して次ページの有無を判定し、next_cursor を作る。出典と置き換えの関係は、返す行ぶんをまとめて読む(行ごとに問い合わせない)。
    # Fetch one extra row to detect whether a next page exists, then build next_cursor. Sources and replacement relations are read
    # for the returned rows together, not one query per row.
    async def operation(db: AsyncSession) -> ContextFactListResponse:
        safe_limit = _safe_list_limit(limit)
        decoded = _decode_cursor(cursor)
        rows = await _repository(db).list_facts(
            user_id,
            fact_type=fact_type,
            status=status,
            query=query,
            limit=safe_limit + 1,
            before_updated_at=decoded[0] if decoded else None,
            before_id=decoded[1] if decoded else None,
        )
        next_cursor = None
        if len(rows) > safe_limit:
            next_cursor = _encode_cursor(rows[safe_limit - 1])
            rows = rows[:safe_limit]
        provenance = await ContextFactProvenanceRepository(db).load(user_id, rows)
        return ContextFactListResponse(
            facts=[_to_list_item_response(row, provenance[int(row["id"])]) for row in rows],
            total_active=await _repository(db).count_active(user_id),
            next_cursor=next_cursor,
        )

    return await in_transaction_with_retry(session, operation)


async def get_fact(
    user_id: int,
    fact_id: int,
    *,
    session: AsyncSession | None = None,
) -> ContextFactResponse:
    return _to_response(await in_transaction_with_retry(session, lambda db: _repository(db).get_fact(user_id, fact_id)))


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
    # 日本語: 冪等性キーがある場合は、キー自体と内容の 2 つのハッシュを作る。
    # 同じキーで内容だけ違う再送を、リポジトリ側で検出できるようにするため。
    # English: With an idempotency key, build two hashes (key and payload) so the repository can
    # detect a retry that reuses the key with different content.
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

    fact = await in_transaction_with_retry(
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
    # 日本語: 呼び出し側が session を管理している場合と、冪等な再送の場合は、埋め込みを予約しない。
    # English: No embedding is scheduled when the caller owns the session or the request was an idempotent replay.
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
    confirmed_by_owner: bool = False,
    session: AsyncSession | None = None,
) -> ContextFactResponse:
    # confirmed_by_owner は Web UI（本人）の編集だけが True にする。既定 False は MCP などの外部書き込み。
    # Only the owner's web UI edits pass True; the False default is for external writers such as MCP.
    fact = await in_transaction_with_retry(
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
            confirmed_by_owner=confirmed_by_owner,
        ),
    )
    # 日本語: 更新後に有効（active）な事実だけ、埋め込みを作り直す。
    # English: Regenerate the embedding only if the fact is active after the update.
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


# 日本語: 置き換えで入った新しい記憶を無効化し(この内容は再び覚えない)、置き換えられた古い記憶を有効へ戻す(記憶の画面の「元に戻す」)。
# 古い記憶は有効へ戻るので、update_fact の復元と同じく埋め込みを予約する。
# English: Deprecate the memory that came in by replacement (that content is not remembered again) and make the older memory it
# replaced active again (the memory screen's "undo"). The older memory is active again, so an embedding is scheduled as
# update_fact's restore does.
async def revert_replacement(
    user_id: int,
    fact_id: int,
    *,
    expected_revision: int,
    session: AsyncSession | None = None,
) -> ContextFactRevertReplacementResponse:
    deprecated, restored = await in_transaction_with_retry(
        session,
        lambda db: ContextFactCurationRepository(db).revert_replacement(user_id, fact_id, expected_revision),
    )
    if session is None:
        schedule_embedding(
            int(restored["id"]),
            str(restored["fact_type"]),
            str(restored["title"]),
            str(restored["content"]),
            int(restored["revision"]),
        )
    return ContextFactRevertReplacementResponse(fact=_to_response(deprecated), restored_fact=_to_response(restored))


# 日本語: 記憶 1 件を、有効・無効化済みのどちらでも完全に削除する(出典と、その記憶を指す候補も消える)。
# English: Delete one memory for good, active or deprecated (its sources and the candidates pointing at it go too).
async def delete_fact(
    user_id: int,
    fact_id: int,
    *,
    expected_revision: int,
    session: AsyncSession | None = None,
) -> None:
    await in_transaction_with_retry(session, lambda db: ContextFactCurationRepository(db).delete_fact(user_id, fact_id, expected_revision))


# 日本語: 利用者の記憶・出典・候補をすべて削除し、消した記憶の件数を返す。
# English: Delete all of the user's memories, sources and candidates, and return how many memories were deleted.
async def delete_all_facts(user_id: int, *, session: AsyncSession | None = None) -> int:
    return await in_transaction_with_retry(session, lambda db: ContextFactCurationRepository(db).delete_all_facts(user_id))


async def build_digest(
    user_id: int,
    *,
    limit_per_type: int = DEFAULT_DIGEST_LIMIT_PER_TYPE,
    max_chars: int = DEFAULT_DIGEST_MAX_CHARS,
    session: AsyncSession | None = None,
) -> ContextDigestResponse:
    # 日本語: 重要度・更新日時の高い順に事実を 1 件ずつ足し、種類ごとの件数上限と全体の文字数予算に
    # 収まるものだけを採用する。省略した件数は omitted_count / truncated で呼び出し側に伝える。
    # English: Add facts one by one in order of importance and recency, keeping only those that fit the
    # per-type cap and the overall character budget; omitted facts are reported via omitted_count / truncated.
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

    return await in_transaction_with_retry(session, operation)


async def search_facts(
    user_id: int,
    query: str,
    *,
    mode: ContextSearchMode = "keyword",
    limit: int = DEFAULT_CONTEXT_SEARCH_LIMIT,
    session: AsyncSession | None = None,
) -> ContextSearchResult:
    # 日本語: semantic モードで埋め込みが使えない・失敗・結果ゼロのときは、キーワード検索に切り替える。
    # English: In semantic mode, fall back to keyword search when embeddings are unavailable, fail or return no rows.
    normalized_query = query.strip()
    if not normalized_query:
        raise ApiServiceError(ERROR_SEARCH_QUERY_REQUIRED, 400, status="fail")

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

    return await in_transaction_with_retry(session, operation)


# 日本語: チャットの記憶の検索用に、その利用者の有効な記憶すべてを語の一致と意味の近さで順位づけして上位を返す(ADR 0025)。
# 検索語の埋め込みは DB のトランザクションを開く前に作り、失敗・利用不可なら語の一致だけで順位づける。DB の読み取りは 1 回。
# MCP の search_context が使う search_facts は別の関数で、挙動は変えない。埋め込みの失敗は種類だけ記録する。
# English: For chat memory search: rank all of the user's active memory by word match and semantic closeness and return the top ones
# (ADR 0025). The query embedding is made before any DB transaction opens, and when it is unavailable or fails the ranking uses word
# match alone. One DB read. search_facts, used by MCP search_context, is a separate function whose behavior is unchanged.
async def search_facts_ranked(
    user_id: int,
    query: str,
    *,
    limit: int = MEMORY_SEARCH_RESULT_LIMIT,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    normalized_query = query.strip()
    if not normalized_query:
        return []
    embedding: list[float] | None = None
    if embeddings_available():
        try:
            embedding = await asyncio.to_thread(generate_embedding, normalized_query)
        except Exception as exc:
            logger.warning("Failed to generate a memory search embedding; ranking by word match only (%s).", type(exc).__name__)
    rows = await in_transaction_with_retry(session, lambda db: _repository(db).list_active_for_memory_search(user_id, embedding))
    return [dict(row) for row in rank_memory_facts(rows, normalized_query, limit=limit)]


# 日本語: 保存した記憶をチャットの回答に使う設定。保存する設定（context_vault_candidate_service の抽出設定）とは別。
# English: The setting for using saved memory in chat answers; separate from the extraction setting that decides saving.
async def get_memory_use_settings(
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> ContextMemoryUseSettingsResponse:
    enabled = await in_transaction_with_retry(session, lambda db: _repository(db).get_memory_use_enabled(user_id))
    return ContextMemoryUseSettingsResponse(enabled=enabled)


async def update_memory_use_settings(
    user_id: int,
    enabled: bool,
    *,
    session: AsyncSession | None = None,
) -> ContextMemoryUseSettingsResponse:
    updated = await in_transaction_with_retry(session, lambda db: _repository(db).update_memory_use_enabled(user_id, enabled))
    return ContextMemoryUseSettingsResponse(enabled=updated)
