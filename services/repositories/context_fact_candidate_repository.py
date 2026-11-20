"""記憶(context_facts)の自動抽出の保存先を永続化する。抽出した内容は有効件数に空きがあれば事実として直接保存し、
上限で入らない分だけ承認待ち候補(レビュー待ちキュー)に入れる。候補の一覧・承認・却下と、自動抽出の設定も扱う。
承認すると候補が正式な context fact に昇格する。services/context_vault_candidate_service.py から使われる。

Async SQLAlchemy persistence for automatically extracted memory.
Extracted content is saved directly as facts while active slots remain; only what the cap rejects goes to the
pending-candidate review queue. Also covers listing, approving and rejecting candidates and the extraction setting.
Approving a candidate promotes it to a context fact; used by services/context_vault_candidate_service.py.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, cast, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.context_vault_bm25 import find_bm25_duplicates
from services.datetime_serialization import serialize_datetime_iso
from services.error_messages import (
    ERROR_CONTEXT_EXTRACTION_SETTINGS_NOT_FOUND,
    ERROR_CONTEXT_FACT_CANDIDATE_NOT_FOUND,
    ERROR_CONTEXT_FACT_CANDIDATE_REVISION_CONFLICT,
    ERROR_CONTEXT_FACT_LIMIT_REACHED,
)
from services.models import ContextFact, ContextFactCandidate, ContextFactSource, User
from services.repositories.context_fact_repository import MAX_ACTIVE_CONTEXT_FACTS
from services.repositories.context_fact_source_repository import ContextFactSourceRepository

logger = logging.getLogger(__name__)

# 日本語: 重複判定(BM25)に使う既存文書の最大件数。
# English: The maximum number of existing documents used for BM25 duplicate detection.
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

    async def store_extracted(
        self,
        user_id: int,
        candidates: list[dict[str, Any]],
        *,
        room_id: str | None = None,
        user_message_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """重複を除いた抽出結果を、未確認の事実として保存する。有効件数が上限のときは、自動保存のまま本人が手を入れていない
        事実を 1 件ずつ無効化(理由 capacity)して入れ替える。保存した事実の一覧を返す。

        重複判定は、有効な事実・本人が無効化した事実(理由 user か未記録)・本人が却下した候補との BM25 と、却下済み候補の
        fingerprint で行う。上限で外した事実(capacity)と、承認待ち・承認済みの候補は比較しないので、外れた内容が再び話題に
        なれば新しい事実として保存できる。入れ替えられる事実が無いときは、新しい内容を保存しない。
        room_id があり候補に evidence(本人発話の引用)があるときは出典行を残す。保存した事実には同じトランザクションで
        1 件入れ、有効な事実と重複した分は、その事実へ出典を足す(事実の行は更新しない)。

        Save unique extracted content as unconfirmed facts. At the active-fact cap, replace facts one at a time by
        deprecating an auto-saved fact the owner never touched (reason capacity). Returns the facts saved.
        Duplicates are judged by BM25 against active facts, facts the owner deprecated (reason user or unrecorded) and
        rejected candidates, plus the fingerprint of rejected candidates. Facts the cap removed (capacity) and
        pending/approved candidates are not compared, so content that was pushed out can be saved again as a new
        fact. With nothing replaceable, the new content is not saved.
        With a room_id and a candidate evidence quote, a source row is kept: one in the same transaction for a saved
        fact, and one added to the matched fact when the content duplicates an active fact (the fact row is not updated).
        """
        await self._lock_user(user_id)
        active_count = await self.session.scalar(
            select(func.count(ContextFact.id)).where(
                ContextFact.user_id == user_id,
                ContextFact.status == "active",
            )
        )
        free_fact_slots = max(MAX_ACTIVE_CONTEXT_FACTS - int(active_count or 0), 0)

        facts_result = await self.session.execute(
            select(
                ContextFact.id,
                ContextFact.revision,
                ContextFact.fact_type,
                ContextFact.title,
                ContextFact.content,
                ContextFact.updated_at,
                ContextFact.status,
            ).where(
                ContextFact.user_id == user_id,
                # 日本語: 上限で外した事実(capacity)は、本人が取り消したわけではないので比較しない。理由が NULL の無効化済みの事実は
                # この列の追加前の記録で、本人が無効化したものとして扱う。
                # English: A fact the cap removed (capacity) is not something the owner undid, so it is not compared. A deprecated
                # fact with a NULL reason predates the column and counts as the owner's.
                or_(
                    ContextFact.status == "active",
                    ContextFact.deprecated_reason.is_(None),
                    ContextFact.deprecated_reason == "user",
                ),
            )
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
                ContextFactCandidate.status == "rejected",
            )
        )
        # 日本語: 既存の事実・却下済みの候補を重複判定の比較対象にする。有効な事実を優先(priority 0)し、本人が無効化した
        # 事実は 1、却下済みは最後(2)に回して、上限件数で切ったときに有効な内容を残す。同順位では更新が新しいものが先。
        # English: Existing facts and rejected candidates become the duplicate-check corpus. Active facts rank first (priority 0),
        # facts the owner deprecated next (1) and rejected candidates last (2), so the cap drops the least relevant documents;
        # newer updates win within a rank.
        existing_documents = [
            {
                "fact_id": int(row.id),
                "fact_revision": int(row.revision),
                "fact_status": str(row.status),
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
                "priority": 2,
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
        matches = find_bm25_duplicates(
            candidates,
            existing_documents[:MAX_CONTEXT_DEDUPLICATION_DOCUMENTS],
        )

        saved_facts: list[dict[str, Any]] = []
        replaced_count = 0
        # 日本語: このバッチで保存した事実と再言及を記録した事実は、同じバッチの入れ替えの対象にしない。
        # English: Facts saved or re-mentioned in this batch are never replaced by a later candidate of the same batch.
        protected_fact_ids: set[int] = set()
        replacement_exhausted = False
        for candidate, match in zip(candidates, matches, strict=True):
            if match is not None:
                # 日本語: 有効な事実と重複した分は、その事実への再言及として出典だけを足す。一致相手が同一バッチの候補
                # (fact_id なし)・本人が無効化した事実・却下済みの候補のときは何も保存しない。
                # English: A duplicate of an active fact is a repeat mention, so only a source is added to it. Nothing is
                # saved when the match is a same-batch candidate (no fact_id), a fact the owner deprecated, or a rejected candidate.
                if match.get("fact_status") == "active":
                    protected_fact_ids.add(int(match["fact_id"]))
                    await self._record_source(
                        user_id,
                        int(match["fact_id"]),
                        candidate,
                        room_id,
                        user_message_id,
                        expected_revision=int(match["fact_revision"]),
                    )
                continue
            # 日本語: 本人が却下した候補と同じ fingerprint の内容は、保存しない。
            # English: Content whose fingerprint matches a candidate the owner rejected is not saved.
            already_rejected = await self.session.scalar(
                select(ContextFactCandidate.id).where(
                    ContextFactCandidate.user_id == user_id,
                    ContextFactCandidate.fingerprint == candidate["fingerprint"],
                    ContextFactCandidate.status == "rejected",
                )
            )
            if already_rejected is not None:
                continue
            if len(saved_facts) - replaced_count >= free_fact_slots:
                if replacement_exhausted:
                    continue
                if not await self._deprecate_replaceable_fact(user_id, protected_fact_ids):
                    replacement_exhausted = True
                    continue
                replaced_count += 1
            fact = await self._insert_unconfirmed_fact(user_id, candidate)
            saved_facts.append(fact)
            protected_fact_ids.add(int(fact["id"]))
            await self._record_source(user_id, int(fact["id"]), candidate, room_id, user_message_id)
        if replaced_count:
            logger.info("Replaced memory facts at the cap.", extra={"user_id": user_id, "replaced_count": replaced_count})
        return saved_facts

    # 日本語: 上限のとき、自動保存のまま本人が手を入れていない有効な事実を 1 件無効化して理由 capacity を記録し、入れたかを返す。
    # 対象は source_kind が chat で last_confirmed_at が NULL の事実だけ(本人の手入力・編集・承認、MCP、インポートは外れない)。
    # 最後に話題に出た時刻が最も古いものを選び、同じなら重要度が低いもの、それも同じなら id が小さいもの。
    # 時刻は出典(context_fact_sources.observed_at)の最大値で、出典が無い事実は created_at。observed_at は timestamptz、
    # created_at はタイムゾーン無しなので、created_at を timestamptz へ明示的に変換して比べる。created_at は CURRENT_TIMESTAMP を
    # セッションのタイムゾーンの壁時計で保存した値で、変換も同じタイムゾーンで元の時刻へ戻るため、暗黙の変換に頼らず意図を固定する。
    # 選択と無効化は 1 文で行い、対象の条件を更新側にも繰り返す。選んだ後に本人が編集した行は条件に合わなくなり、無効化されない。
    # English: At the cap, deprecate one active fact that was auto-saved and never touched by the owner, record reason capacity,
    # and return whether one was replaced. Only facts with source_kind chat and a NULL last_confirmed_at qualify (the owner's
    # manual, edited and approved facts, MCP and imports are never removed). The fact last mentioned longest ago goes first,
    # then the lower importance, then the smaller id. Last mention is the newest context_fact_sources.observed_at, or created_at
    # when there is no source. observed_at is timestamptz while created_at is timezone-less, so created_at is cast to timestamptz
    # explicitly: it was stored as the session-timezone wall clock of CURRENT_TIMESTAMP, and the cast reads it back in the same
    # zone, so the comparison does not rely on an implicit conversion. Choosing and deprecating happen in one statement and the
    # eligibility is repeated on the update, so a fact the owner edits in between is no longer eligible and is left alone.
    async def _deprecate_replaceable_fact(self, user_id: int, protected_fact_ids: set[int]) -> bool:
        replaceable = aliased(ContextFact)

        def eligible(model: Any) -> list[Any]:
            conditions = [
                model.user_id == user_id,
                model.status == "active",
                model.source_kind == "chat",
                model.last_confirmed_at.is_(None),
            ]
            if protected_fact_ids:
                conditions.append(model.id.not_in(sorted(protected_fact_ids)))
            return conditions

        last_mentioned = func.coalesce(
            select(func.max(ContextFactSource.observed_at))
            .where(ContextFactSource.fact_id == replaceable.id)
            .scalar_subquery(),
            cast(replaceable.created_at, DateTime(timezone=True)),
        )
        victim = (
            select(replaceable.id)
            .where(*eligible(replaceable))
            .order_by(last_mentioned.asc(), replaceable.importance.asc(), replaceable.id.asc())
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            update(ContextFact)
            .where(ContextFact.id == victim, *eligible(ContextFact))
            .values(
                status="deprecated",
                deprecated_reason="capacity",
                revision=ContextFact.revision + 1,
                updated_at=func.current_timestamp(),
            )
            .returning(ContextFact.id)
        )
        return (await self.session.execute(statement)).scalar_one_or_none() is not None

    # 日本語: 候補の evidence を出典として事実へ残す。部屋か evidence が無いとき(旧形式の呼び出し)は何もしない。
    # expected_revision は既存の事実へ足すときの、重複を判定した時点の revision（新しく作った事実では None）。
    # English: Keep the candidate's evidence as a source of the fact. Does nothing without a room or evidence (older callers).
    # expected_revision is the revision read when the duplicate was judged, for an existing fact (None for a fact just created).
    async def _record_source(
        self,
        user_id: int,
        fact_id: int,
        candidate: dict[str, Any],
        room_id: str | None,
        user_message_id: int | None,
        expected_revision: int | None = None,
    ) -> None:
        evidence = str(candidate.get("evidence") or "")
        if not room_id or not evidence:
            return
        await ContextFactSourceRepository(self.session).record_mention(
            fact_id=fact_id,
            user_id=user_id,
            chat_room_id=room_id,
            user_message_id=user_message_id,
            evidence=evidence,
            expected_revision=expected_revision,
        )

    # 日本語: 抽出した内容を事実として挿入する。last_confirmed_at は書かず NULL(本人未確認)のまま、確信度は抽出時の値を残す。
    # 本人が Web UI で編集すれば確認済みになる(ADR 0016)。
    # English: Insert extracted content as a fact. last_confirmed_at stays NULL (unconfirmed by the owner) and the extraction
    # confidence is kept; an owner edit in the web UI later confirms it (ADR 0016).
    async def _insert_unconfirmed_fact(self, user_id: int, candidate: dict[str, Any]) -> dict[str, Any]:
        statement = pg_insert(ContextFact).values(
            user_id=user_id,
            fact_type=candidate["fact_type"],
            title=candidate["title"],
            content=candidate["content"],
            source_kind=candidate.get("source_kind", "chat"),
            source_ref=candidate.get("source_ref"),
            importance=candidate.get("importance", 50),
            confidence=candidate.get("confidence", 0),
        ).returning(*_FACT_RETURNING)
        row = (await self.session.execute(statement)).mappings().first()
        if row is None:  # pragma: no cover - PostgreSQL RETURNING invariant
            raise RuntimeError("Extracted context fact was not returned.")
        return _serialize_fact(row)

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

    # 日本語: 列は NOT NULL なので None はユーザー行が読めなかったときだけ。その場合は無効として扱い、
    # 読めない相手に抽出が走らないようにする。
    # 初期オンは列の server_default(と migration)だけで表す。
    # English: The column is NOT NULL, so None only means the user row could not be read. That counts as disabled, so no
    # extraction runs for a user we cannot read. The on-by-default behavior lives only in the column's server_default (and the migration).
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
