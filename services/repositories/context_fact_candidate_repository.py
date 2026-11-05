"""My Context の事実候補(レビュー待ちキュー)の保存・一覧・承認・却下と、自動抽出の設定を永続化する。

承認すると候補が正式な context fact に昇格する。services/context_vault_candidate_service.py から使われる。

Async SQLAlchemy persistence for the context-fact review queue.
Approving a candidate promotes it to a context fact; used by services/context_vault_candidate_service.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.context_vault_bm25 import filter_bm25_duplicates
from services.datetime_serialization import serialize_datetime_iso
from services.error_messages import (
    ERROR_CONTEXT_EXTRACTION_SETTINGS_NOT_FOUND,
    ERROR_CONTEXT_FACT_CANDIDATE_NOT_FOUND,
    ERROR_CONTEXT_FACT_CANDIDATE_REVISION_CONFLICT,
    ERROR_CONTEXT_FACT_LIMIT_REACHED,
)
from services.models import ContextFact, ContextFactCandidate, User
from services.repositories.context_fact_repository import MAX_ACTIVE_CONTEXT_FACTS

# 日本語: 承認待ち候補の 1 ユーザーあたり上限と、重複判定(BM25)に使う既存文書の最大件数。
# English: Per-user cap on pending candidates, and the maximum number of existing documents used for BM25 duplicate detection.
MAX_PENDING_CONTEXT_FACT_CANDIDATES = 100
MAX_CONTEXT_DEDUPLICATION_DOCUMENTS = 500
# 日本語: advisory lock の名前空間(第 1 キー)。context_fact_repository と同じ値で、第 2 キーに user_id を渡すため、
# 同一ユーザーの候補と事実の更新が同じロックで直列化される。
# English: Advisory-lock namespace (first key), the same value as in context_fact_repository; with user_id as the second key,
# candidate and fact writes of one user are serialized by the same lock.
_CONTEXT_VAULT_LOCK_NAMESPACE = 1129601108  # ASCII "CTXT"

_CANDIDATE_COLUMNS = (
    "id",
    "user_id",
    "fact_type",
    "title",
    "content",
    "source_kind",
    "source_ref",
    "source_client_id",
    "importance",
    "confidence",
    "status",
    "fingerprint",
    "promoted_fact_id",
    "revision",
    "created_at",
    "updated_at",
)
_FACT_COLUMNS = (
    "id",
    "user_id",
    "fact_type",
    "title",
    "content",
    "source_kind",
    "source_ref",
    "source_client_id",
    "importance",
    "status",
    "revision",
    "confidence",
    "last_confirmed_at",
    "created_at",
    "updated_at",
)
_CANDIDATE_RETURNING = tuple(getattr(ContextFactCandidate, name) for name in _CANDIDATE_COLUMNS)
_FACT_RETURNING = tuple(getattr(ContextFact, name) for name in _FACT_COLUMNS)


# 日本語: ORM モデル・Row・マッピングのどれが来ても、指定列だけの dict にそろえる(RETURNING の結果と ORM 行
# を同じ関数でシリアライズするため)。
# English: Normalizes an ORM model, Row or mapping into a dict of the given columns so RETURNING results and ORM rows share one serializer.
def _record(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(row, (ContextFactCandidate, ContextFact, User)):
        return {name: getattr(row, name) for name in columns}
    mapping = row if hasattr(row, "keys") else getattr(row, "_mapping", row)
    return {
        name: mapping[name] if name in mapping else getattr(mapping, name, None)
        for name in columns
    }


def _serialize_candidate(row: Any) -> dict[str, Any]:
    record = _record(row, _CANDIDATE_COLUMNS)
    return {
        "id": int(record["id"]),
        "user_id": int(record["user_id"]),
        "fact_type": str(record["fact_type"]),
        "title": str(record["title"] or ""),
        "content": str(record["content"] or ""),
        "source_kind": str(record["source_kind"] or "chat"),
        "source_ref": str(record["source_ref"]) if record["source_ref"] is not None else None,
        "source_client_id": (
            str(record["source_client_id"])
            if record["source_client_id"] is not None
            else None
        ),
        "importance": int(record["importance"] if record["importance"] is not None else 50),
        "confidence": float(record["confidence"] or 0),
        "status": str(record["status"] or "pending"),
        "fingerprint": str(record["fingerprint"]),
        "promoted_fact_id": (
            int(record["promoted_fact_id"])
            if record["promoted_fact_id"] is not None
            else None
        ),
        "revision": max(int(record["revision"] or 1), 1),
        "created_at": serialize_datetime_iso(record["created_at"]),
        "updated_at": serialize_datetime_iso(record["updated_at"]),
    }


def _serialize_fact(row: Any) -> dict[str, Any]:
    record = _record(row, _FACT_COLUMNS)
    return {
        "id": int(record["id"]),
        "user_id": int(record["user_id"]),
        "fact_type": str(record["fact_type"]),
        "title": str(record["title"] or ""),
        "content": str(record["content"] or ""),
        "source_kind": str(record["source_kind"] or "chat"),
        "source_ref": str(record["source_ref"]) if record["source_ref"] is not None else None,
        "source_client_id": (
            str(record["source_client_id"])
            if record["source_client_id"] is not None
            else None
        ),
        "importance": int(record["importance"] if record["importance"] is not None else 50),
        "status": str(record["status"] or "active"),
        "revision": max(int(record["revision"] or 1), 1),
        "confidence": float(record["confidence"]) if record["confidence"] is not None else None,
        "last_confirmed_at": serialize_datetime_iso(record["last_confirmed_at"]),
        "created_at": serialize_datetime_iso(record["created_at"]),
        "updated_at": serialize_datetime_iso(record["updated_at"]),
    }


class ContextFactCandidateRepository:
    """所有ユーザーで絞った候補の永続化。トランザクションは呼び出し側が持つ。

    Owner-scoped candidate persistence; transaction ownership stays with the caller.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # 日本語: トランザクション終了まで続くユーザー単位のロック。上限判定や重複判定と挿入の間に別リクエストが割り込むのを防ぐ。
    # English: Transaction-scoped per-user lock, so another request cannot slip in between the cap/duplicate checks and the insert.
    async def _lock_user(self, user_id: int) -> None:
        await self.session.execute(
            select(func.pg_advisory_xact_lock(_CONTEXT_VAULT_LOCK_NAMESPACE, user_id))
        )

    async def store_candidates(self, user_id: int, candidates: list[dict[str, Any]]) -> int:
        """重複を除いた候補を、ユーザーごとの承認待ち上限まで挿入し、挿入件数を返す。

        Insert unique candidates up to the per-user pending cap.
        """
        await self._lock_user(user_id)
        pending_count = await self.session.scalar(
            select(func.count(ContextFactCandidate.id)).where(
                ContextFactCandidate.user_id == user_id,
                ContextFactCandidate.status == "pending",
            )
        )
        remaining = max(MAX_PENDING_CONTEXT_FACT_CANDIDATES - int(pending_count or 0), 0)
        if remaining == 0:
            return 0

        facts_result = await self.session.execute(
            select(
                ContextFact.fact_type,
                ContextFact.title,
                ContextFact.content,
                ContextFact.updated_at,
                ContextFact.status,
            ).where(ContextFact.user_id == user_id)
        )
        candidates_result = await self.session.execute(
            select(
                ContextFactCandidate.fact_type,
                ContextFactCandidate.title,
                ContextFactCandidate.content,
                ContextFactCandidate.updated_at,
                ContextFactCandidate.status,
            ).where(
                ContextFactCandidate.user_id == user_id,
                ContextFactCandidate.status.in_(("pending", "rejected")),
            )
        )
        # 日本語: 既存の事実・候補を重複判定の比較対象にする。active の事実と pending の候補を優先(priority 0)し、
        # 却下済みは最後(2)に回して、上限件数で切ったときに有効な内容を残す。同順位では更新が新しいものが先。
        # English: Existing facts and candidates become the duplicate-check corpus. Active facts and pending candidates rank first
        # (priority 0) and rejected ones last (2), so the cap drops the least relevant documents; newer updates win within a rank.
        existing_documents = [
            {
                "fact_type": str(row.fact_type),
                "title": str(row.title or ""),
                "content": str(row.content or ""),
                "updated_at": row.updated_at,
                "priority": 0 if row.status == "active" else 1,
            }
            for row in facts_result
        ] + [
            {
                "fact_type": str(row.fact_type),
                "title": str(row.title or ""),
                "content": str(row.content or ""),
                "updated_at": row.updated_at,
                "priority": 0 if row.status == "pending" else 2,
            }
            for row in candidates_result
        ]
        existing_documents.sort(
            key=lambda document: (
                int(document["priority"]),
                -(
                    document["updated_at"].timestamp()
                    if document["updated_at"] is not None
                    else float("-inf")
                ),
            )
        )
        unique_candidates = filter_bm25_duplicates(
            candidates,
            existing_documents[:MAX_CONTEXT_DEDUPLICATION_DOCUMENTS],
        )

        # 日本語: 同じ fingerprint の候補は挿入しない。事前確認に加え、承認待ちに限る部分ユニーク索
        # 引への ON CONFLICT DO NOTHING で並行挿入も防ぐ。
        # English: Candidates with an existing fingerprint are skipped; ON CONFLICT DO NOTHING on the pending-only partial unique index
        # also covers concurrent inserts beyond the up-front check.
        inserted = 0
        for candidate in unique_candidates:
            if inserted >= remaining:
                break
            already_exists = await self.session.scalar(
                select(ContextFactCandidate.id).where(
                    ContextFactCandidate.user_id == user_id,
                    ContextFactCandidate.fingerprint == candidate["fingerprint"],
                )
            )
            if already_exists is not None:
                continue
            statement = pg_insert(ContextFactCandidate).values(
                user_id=user_id,
                fact_type=candidate["fact_type"],
                title=candidate["title"],
                content=candidate["content"],
                source_kind=candidate.get("source_kind", "chat"),
                source_ref=candidate.get("source_ref"),
                source_client_id=candidate.get("source_client_id"),
                importance=candidate.get("importance", 50),
                confidence=candidate.get("confidence", 0),
                fingerprint=candidate["fingerprint"],
            ).on_conflict_do_nothing(
                index_elements=[ContextFactCandidate.user_id, ContextFactCandidate.fingerprint],
                index_where=ContextFactCandidate.status == "pending",
            ).returning(ContextFactCandidate.id)
            if (await self.session.execute(statement)).scalar_one_or_none() is not None:
                inserted += 1
        return inserted

    # 日本語: (created_at, id) の降順によるキーセットページング。before_* を渡すとそれより古い行だけを返す。
    # English: Keyset pagination ordered by (created_at, id) descending; before_* restricts the result to older rows.
    async def list_candidates(
        self,
        user_id: int,
        *,
        status: str = "pending",
        limit: int = 21,
        before_created_at: datetime | None = None,
        before_id: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions = [
            ContextFactCandidate.user_id == user_id,
            ContextFactCandidate.status == status,
        ]
        if before_created_at is not None and before_id is not None:
            conditions.append(
                tuple_(ContextFactCandidate.created_at, ContextFactCandidate.id)
                < tuple_(before_created_at, before_id)
            )
        result = await self.session.execute(
            select(ContextFactCandidate)
            .where(*conditions)
            .order_by(ContextFactCandidate.created_at.desc(), ContextFactCandidate.id.desc())
            .limit(limit)
        )
        return [_serialize_candidate(row) for row in result.scalars().all()]

    async def count_pending(self, user_id: int) -> int:
        count = await self.session.scalar(
            select(func.count(ContextFactCandidate.id)).where(
                ContextFactCandidate.user_id == user_id,
                ContextFactCandidate.status == "pending",
            )
        )
        return int(count or 0)

    async def approve_candidate(
        self,
        user_id: int,
        candidate_id: int,
        *,
        expected_revision: int,
        fact_type: str | None = None,
        title: str | None = None,
        content: str | None = None,
        importance: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """承認待ちの候補を事実へ昇格させ、候補を承認済みにする(同一トランザクション)。

        expected_revision が一致しないとき(他の操作で更新済み)は 409 で拒否する。

        Promote a pending candidate and approve it atomically.
        """
        await self._lock_user(user_id)
        candidate_model = await self.session.scalar(
            select(ContextFactCandidate)
            .where(
                ContextFactCandidate.id == candidate_id,
                ContextFactCandidate.user_id == user_id,
            )
            .with_for_update()
        )
        if candidate_model is None:
            raise ResourceNotFoundError(ERROR_CONTEXT_FACT_CANDIDATE_NOT_FOUND)
        candidate = _serialize_candidate(candidate_model)
        if candidate["status"] != "pending" or candidate["revision"] != expected_revision:
            raise ApiServiceError(
                ERROR_CONTEXT_FACT_CANDIDATE_REVISION_CONFLICT,
                409,
                status="fail",
            )

        active_count = await self.session.scalar(
            select(func.count(ContextFact.id)).where(
                ContextFact.user_id == user_id,
                ContextFact.status == "active",
            )
        )
        if int(active_count or 0) >= MAX_ACTIVE_CONTEXT_FACTS:
            raise ApiServiceError(ERROR_CONTEXT_FACT_LIMIT_REACHED, 409, status="fail")

        fact_statement = pg_insert(ContextFact).values(
            user_id=user_id,
            fact_type=fact_type if fact_type is not None else candidate["fact_type"],
            title=title if title is not None else candidate["title"],
            content=content if content is not None else candidate["content"],
            source_kind=candidate["source_kind"],
            source_ref=candidate["source_ref"],
            source_client_id=candidate["source_client_id"],
            importance=importance if importance is not None else candidate["importance"],
            # 承認は本人が内容を見て確かめた行為。抽出時の確信度を残し、確認時刻は今にする。
            # Approval is the owner reviewing the content: keep the extraction confidence and stamp now.
            confidence=candidate["confidence"],
            last_confirmed_at=func.current_timestamp(),
        ).returning(*_FACT_RETURNING)
        fact_row = (await self.session.execute(fact_statement)).mappings().first()
        if fact_row is None:  # pragma: no cover - PostgreSQL RETURNING invariant
            raise RuntimeError("Promoted context fact was not returned.")
        fact = _serialize_fact(fact_row)

        # 日本語: 状態と revision を条件に含めた UPDATE で楽観ロックし、取得後に変更されていたら 0 行になって競合として扱う。
        # English: The UPDATE repeats the status and revision conditions as optimistic locking; zero rows means it changed meanwhile.
        candidate_statement = (
            update(ContextFactCandidate)
            .where(
                ContextFactCandidate.id == candidate_id,
                ContextFactCandidate.user_id == user_id,
                ContextFactCandidate.status == "pending",
                ContextFactCandidate.revision == expected_revision,
            )
            .values(
                status="approved",
                promoted_fact_id=fact["id"],
                revision=ContextFactCandidate.revision + 1,
                updated_at=func.current_timestamp(),
            )
            .returning(*_CANDIDATE_RETURNING)
        )
        approved_row = (await self.session.execute(candidate_statement)).mappings().first()
        if approved_row is None:
            raise ApiServiceError(
                ERROR_CONTEXT_FACT_CANDIDATE_REVISION_CONFLICT,
                409,
                status="fail",
            )
        return _serialize_candidate(approved_row), fact

    # 日本語: 却下。更新できなかった場合は、候補が無い(404)のか revision/状態の不一致(409)なのかを再確認して区別する。
    # English: Rejects a candidate. When the update matches nothing, a follow-up lookup tells "not found"
    # (404) from a revision/status conflict (409).
    async def reject_candidate(
        self,
        user_id: int,
        candidate_id: int,
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        statement = (
            update(ContextFactCandidate)
            .where(
                ContextFactCandidate.id == candidate_id,
                ContextFactCandidate.user_id == user_id,
                ContextFactCandidate.status == "pending",
                ContextFactCandidate.revision == expected_revision,
            )
            .values(
                status="rejected",
                revision=ContextFactCandidate.revision + 1,
                updated_at=func.current_timestamp(),
            )
            .returning(*_CANDIDATE_RETURNING)
        )
        row = (await self.session.execute(statement)).mappings().first()
        if row is not None:
            return _serialize_candidate(row)
        exists_for_owner = await self.session.scalar(
            select(ContextFactCandidate.id).where(
                ContextFactCandidate.id == candidate_id,
                ContextFactCandidate.user_id == user_id,
            )
        )
        if exists_for_owner is None:
            raise ResourceNotFoundError(ERROR_CONTEXT_FACT_CANDIDATE_NOT_FOUND)
        raise ApiServiceError(
            ERROR_CONTEXT_FACT_CANDIDATE_REVISION_CONFLICT,
            409,
            status="fail",
        )

    async def get_extraction_settings(self, user_id: int) -> bool:
        enabled = await self.session.scalar(
            select(User.context_auto_extract_enabled).where(User.id == user_id)
        )
        return bool(enabled) if enabled is not None else False

    async def update_extraction_settings(self, user_id: int, enabled: bool) -> bool:
        statement = (
            update(User)
            .where(User.id == user_id)
            .values(context_auto_extract_enabled=bool(enabled))
            .returning(User.context_auto_extract_enabled)
        )
        result = await self.session.execute(statement)
        value = result.scalar_one_or_none()
        if value is None:
            raise ResourceNotFoundError(ERROR_CONTEXT_EXTRACTION_SETTINGS_NOT_FOUND)
        return bool(value)

    # 日本語: 自動抽出を実行してよいか。ユーザー設定が有効で、承認待ちが上限未満のときだけ True(キューが満杯なら抽出しない)。
    # English: Whether auto-extraction may run: enabled for the user and the pending queue is below its cap (no extraction when full).
    async def should_extract_context(self, user_id: int) -> bool:
        pending_count = (
            select(func.count(ContextFactCandidate.id))
            .where(
                ContextFactCandidate.user_id == User.id,
                ContextFactCandidate.status == "pending",
            )
            .scalar_subquery()
        )
        row = (
            await self.session.execute(
                select(User.context_auto_extract_enabled, pending_count < MAX_PENDING_CONTEXT_FACT_CANDIDATES)
                .where(User.id == user_id)
            )
        ).first()
        return bool(row and row[0] and row[1])
