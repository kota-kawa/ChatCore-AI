"""個人のコンテキスト保管庫(My Context の事実 = context_facts)の永続化。一覧、検索(意味・テキスト)、作成、一括取り込み、更新を扱う。

更新は revision による楽観ロック、作成は idempotency キーによる重複防止を持つ。services 側のコンテキスト保管庫サービスから使われる。

Async SQLAlchemy persistence for the personal context vault.
Updates use revision-based optimistic locking and creation supports idempotency keys.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import (
    and_,
    bindparam,
    case,
    column,
    exists,
    func,
    literal,
    null,
    or_,
    select,
    tuple_,
    update,
    values,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.datetime_serialization import serialize_datetime_iso
from services.embeddings import get_semantic_max_distance
from services.error_messages import (
    ERROR_CONTEXT_FACT_IDEMPOTENCY_CONFLICT,
    ERROR_CONTEXT_FACT_LIMIT_REACHED,
    ERROR_CONTEXT_FACT_NOT_FOUND,
    ERROR_CONTEXT_FACT_REVISION_CONFLICT,
)
from services.models import ContextFact
from services.models.types import Vector
from services.search_terms import build_like_pattern, split_search_terms

# 日本語: 有効(active)な事実の 1 ユーザーあたり上限。
# English: Per-user cap on active facts.
MAX_ACTIVE_CONTEXT_FACTS = 200
# 日本語: advisory lock の名前空間。候補リポジトリと同じ値で、同一ユーザーの事実/候補の書き込みを直列化する。
# English: Advisory-lock namespace, shared with the candidate repository so one user's fact/candidate writes are serialized.
_CONTEXT_FACT_LOCK_NAMESPACE = 1129601108  # ASCII "CTXT"

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
    "idempotency_key_hash",
    "idempotency_payload_hash",
    "status",
    "revision",
    "embedding_status",
    "confidence",
    "last_confirmed_at",
    "created_at",
    "updated_at",
)
_FACT_RETURNING_COLUMNS = tuple(getattr(ContextFact, name) for name in _FACT_COLUMNS)


def _record_from_row(row: Any) -> dict[str, Any]:
    if isinstance(row, ContextFact):
        return {name: getattr(row, name) for name in _FACT_COLUMNS}
    mapping = row if isinstance(row, Mapping) else getattr(row, "_mapping", row)
    return {
        name: mapping[name] if name in mapping else getattr(mapping, name, None)
        for name in _FACT_COLUMNS
    }


def _serialize_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(record["id"]),
        "user_id": int(record["user_id"]),
        "fact_type": str(record["fact_type"]),
        "title": str(record["title"] or ""),
        "content": str(record["content"] or ""),
        "source_kind": str(record["source_kind"] or "manual"),
        "source_ref": str(record["source_ref"]) if record["source_ref"] is not None else None,
        "source_client_id": (
            str(record["source_client_id"])
            if record["source_client_id"] is not None
            else None
        ),
        "importance": int(record["importance"] if record["importance"] is not None else 50),
        "idempotency_key_hash": (
            str(record["idempotency_key_hash"])
            if record["idempotency_key_hash"] is not None
            else None
        ),
        "idempotency_payload_hash": (
            str(record["idempotency_payload_hash"])
            if record["idempotency_payload_hash"] is not None
            else None
        ),
        "status": str(record["status"] or "active"),
        "revision": max(int(record["revision"] or 1), 1),
        "confidence": float(record["confidence"]) if record["confidence"] is not None else None,
        "last_confirmed_at": serialize_datetime_iso(record["last_confirmed_at"]),
        "created_at": serialize_datetime_iso(record["created_at"]),
        "updated_at": serialize_datetime_iso(record["updated_at"]),
        "_updated_at_raw": record["updated_at"],
    }


class ContextFactRepository:
    # context_factsの永続化境界。複数操作を原子的にまとめるため、commitとrollbackは呼び出し元が担う。
    """Persistence boundary for ``context_facts``.

    The repository never commits or rolls back.  The caller owns the
    ``AsyncSession`` transaction so a use case can combine several operations
    atomically.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _serialize_row(row: Any) -> dict[str, Any]:
        return _serialize_record(_record_from_row(row))

    # 日本語: トランザクション終了までのユーザー単位ロック。件数上限の確認と挿入の間に別の書き込みが入らないようにする。
    # English: Transaction-scoped per-user lock, so no other write lands between the cap check and the insert.
    async def _lock_user_writes(self, user_id: int) -> None:
        await self.session.execute(
            select(func.pg_advisory_xact_lock(_CONTEXT_FACT_LOCK_NAMESPACE, user_id))
        )

    async def count_active(self, user_id: int) -> int:
        count = await self.session.scalar(
            select(func.count(ContextFact.id)).where(
                ContextFact.user_id == user_id,
                ContextFact.status == "active",
            )
        )
        return int(count or 0)

    # 日本語: (updated_at, id) の降順によるキーセットページング。before_* より古い行だけを返す。
    # English: Keyset pagination ordered by (updated_at, id) descending; only rows older than before_* are returned.
    async def list_facts(
        self,
        user_id: int,
        *,
        fact_type: str | None = None,
        status: str = "active",
        limit: int = 50,
        before_updated_at: datetime | None = None,
        before_id: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions = [ContextFact.user_id == user_id, ContextFact.status == status]
        if fact_type is not None:
            conditions.append(ContextFact.fact_type == fact_type)
        if before_updated_at is not None and before_id is not None:
            conditions.append(
                tuple_(ContextFact.updated_at, ContextFact.id)
                < tuple_(literal(before_updated_at), literal(before_id))
            )
        result = await self.session.execute(
            select(ContextFact)
            .where(*conditions)
            .order_by(ContextFact.updated_at.desc(), ContextFact.id.desc())
            .limit(limit)
        )
        return [self._serialize_row(fact) for fact in result.scalars().all()]

    # 日本語: LLM へ渡す要約用に、有効な事実を重要度の高い順(同順位は新しい順)で上限件数まで返す。
    # English: Returns active facts for the LLM digest, most important first (newest first on ties), up to the cap.
    async def list_active_for_digest(self, user_id: int) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(ContextFact)
            .where(ContextFact.user_id == user_id, ContextFact.status == "active")
            .order_by(
                ContextFact.importance.desc(),
                ContextFact.updated_at.desc(),
                ContextFact.id.desc(),
            )
            .limit(MAX_ACTIVE_CONTEXT_FACTS)
        )
        return [self._serialize_row(fact) for fact in result.scalars().all()]

    async def list_all_facts(
        self,
        user_id: int,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        statement = (
            select(ContextFact)
            .where(ContextFact.user_id == user_id)
            .order_by(ContextFact.created_at.asc(), ContextFact.id.asc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self.session.execute(statement)
        return [self._serialize_row(fact) for fact in result.scalars().all()]

    async def find_existing_portable_signatures(
        self,
        user_id: int,
        facts: list[dict[str, Any]],
    ) -> set[tuple[str, str, str, str, int]]:
        # PostgreSQLのVALUES CTEでインポート時の完全一致重複を探す。
        """Find exact import duplicates with a PostgreSQL ``VALUES`` CTE."""
        if not facts:
            return set()
        imported = values(
            column("fact_type"),
            column("title"),
            column("content"),
            column("status"),
            column("importance"),
            name="imported",
        ).data(
            [
                (
                    fact["fact_type"],
                    fact["title"],
                    fact["content"],
                    fact["status"],
                    fact["importance"],
                )
                for fact in facts
            ]
        ).cte("imported")
        statement = (
            select(
                imported.c.fact_type,
                imported.c.title,
                imported.c.content,
                imported.c.status,
                imported.c.importance,
            )
            .select_from(
                imported.join(
                    ContextFact,
                    and_(
                        ContextFact.user_id == user_id,
                        ContextFact.fact_type == imported.c.fact_type,
                        ContextFact.title == imported.c.title,
                        ContextFact.content == imported.c.content,
                        ContextFact.status == imported.c.status,
                        ContextFact.importance == imported.c.importance,
                    ),
                )
            )
            .distinct()
        )
        rows = (await self.session.execute(statement)).all()
        return {
            (str(row[0]), str(row[1]), str(row[2]), str(row[3]), int(row[4]))
            for row in rows
        }

    async def get_fact(self, user_id: int, fact_id: int) -> dict[str, Any]:
        fact = await self.session.scalar(
            select(ContextFact).where(
                ContextFact.id == fact_id,
                ContextFact.user_id == user_id,
            )
        )
        if fact is None:
            raise ResourceNotFoundError(ERROR_CONTEXT_FACT_NOT_FOUND)
        return self._serialize_row(fact)

    # 日本語: pgvector のコサイン距離演算子(<=>)で、クエリ埋め込み(768 次元)との距離の式を作る。
    # English: Builds the pgvector cosine-distance expression (<=>) against the 768-dimension query embedding.
    @staticmethod
    def _distance(embedding: list[float]):
        query_vector = bindparam(
            "context_query_embedding",
            value=[float(value) for value in embedding],
            type_=Vector(768),
        )
        return ContextFact.embedding_vector.op("<=>")(query_vector)

    # 日本語: 埋め込みのある行だけを対象に、距離が設定された最大距離以内のものを近い順に返す。
    # English: Searches only rows that have an embedding, returning those within the configured max distance, nearest first.
    async def semantic_search(
        self,
        user_id: int,
        embedding: list[float],
        *,
        limit: int = 20,
        status: str = "active",
    ) -> list[dict[str, Any]]:
        distance = self._distance(embedding)
        result = await self.session.execute(
            select(ContextFact)
            .where(
                ContextFact.user_id == user_id,
                ContextFact.status == status,
                ContextFact.embedding_vector.is_not(None),
                distance <= get_semantic_max_distance(),
            )
            .order_by(distance)
            .limit(limit)
        )
        return [self._serialize_row(fact) for fact in result.scalars().all()]

    # 日本語: 語ごとに title/content の部分一致(ILIKE)を AND で重ねる簡易検索。新しい更新順に返す。
    # English: Simple search that ANDs a title/content ILIKE match per term, newest update first.
    async def text_search(
        self,
        user_id: int,
        query: str,
        *,
        limit: int = 20,
        status: str = "active",
    ) -> list[dict[str, Any]]:
        conditions = [ContextFact.user_id == user_id, ContextFact.status == status]
        for term in split_search_terms(query):
            pattern = build_like_pattern(term)
            conditions.append(
                ContextFact.title.ilike(pattern, escape="\\")
                | ContextFact.content.ilike(pattern, escape="\\")
            )
        result = await self.session.execute(
            select(ContextFact)
            .where(*conditions)
            .order_by(ContextFact.updated_at.desc(), ContextFact.id.desc())
            .limit(limit)
        )
        return [self._serialize_row(fact) for fact in result.scalars().all()]

    async def create_fact(
        self,
        user_id: int,
        *,
        fact_type: str,
        title: str,
        content: str,
        source_kind: str = "manual",
        source_ref: str | None = None,
        source_client_id: str | None = None,
        importance: int = 50,
        idempotency_key_hash: str | None = None,
        idempotency_payload_hash: str | None = None,
    ) -> dict[str, Any]:
        # 日本語: 同じ idempotency キーの再送は、内容が同じなら既存行を再生(_idempotent_replay)し、内容が違えば 409 にする。
        # English: A retry with the same idempotency key replays the existing row (_idempotent_replay) if the payload matches, else 409.
        await self._lock_user_writes(user_id)
        if idempotency_key_hash is not None:
            existing = await self.session.scalar(
                select(ContextFact).where(
                    ContextFact.user_id == user_id,
                    ContextFact.idempotency_key_hash == idempotency_key_hash,
                )
            )
            if existing is not None:
                serialized = self._serialize_row(existing)
                if serialized["idempotency_payload_hash"] != idempotency_payload_hash:
                    raise ApiServiceError(
                        ERROR_CONTEXT_FACT_IDEMPOTENCY_CONFLICT,
                        409,
                        status="fail",
                    )
                serialized["_idempotent_replay"] = True
                return serialized

        if await self.count_active(user_id) >= MAX_ACTIVE_CONTEXT_FACTS:
            raise ApiServiceError(ERROR_CONTEXT_FACT_LIMIT_REACHED, 409, status="fail")

        # 本人が Web UI で書いた事実（manual）だけを作成時点で確認済みにする。MCP は本人の承認なしに
        # 保存されるので NULL（未確認）のまま。ADR 0016。
        # Only facts the owner typed in the web UI (manual) start out confirmed. MCP saves without
        # the owner's approval, so it stays NULL (unconfirmed). ADR 0016.
        statement = (
            pg_insert(ContextFact)
            .values(
                user_id=user_id,
                fact_type=fact_type,
                title=title,
                content=content,
                source_kind=source_kind,
                source_ref=source_ref,
                source_client_id=source_client_id,
                importance=importance,
                idempotency_key_hash=idempotency_key_hash,
                idempotency_payload_hash=idempotency_payload_hash,
                last_confirmed_at=func.current_timestamp() if source_kind == "manual" else None,
            )
            .on_conflict_do_nothing(index_elements=[ContextFact.idempotency_key_hash])
            .returning(*_FACT_RETURNING_COLUMNS)
        )
        row = (await self.session.execute(statement)).mappings().first()
        if row is not None:
            return self._serialize_row(row)

        # 日本語: 挿入が ON CONFLICT で何も返さなかった場合は、ロック取得後でも同じキーが先に入ったことを意味するので、もう一度照合する。
        # English: If ON CONFLICT returned nothing, the same key was inserted first; look it up again and replay or report a conflict.
        if idempotency_key_hash is not None:
            existing = await self.session.scalar(
                select(ContextFact).where(
                    ContextFact.user_id == user_id,
                    ContextFact.idempotency_key_hash == idempotency_key_hash,
                )
            )
            if existing is not None:
                serialized = self._serialize_row(existing)
                if serialized["idempotency_payload_hash"] != idempotency_payload_hash:
                    raise ApiServiceError(
                        ERROR_CONTEXT_FACT_IDEMPOTENCY_CONFLICT,
                        409,
                        status="fail",
                    )
                serialized["_idempotent_replay"] = True
                return serialized
        raise ApiServiceError(ERROR_CONTEXT_FACT_IDEMPOTENCY_CONFLICT, 409, status="fail")

    async def bulk_import_facts(
        self,
        user_id: int,
        facts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """取り込みバッチを一括で追加し、完全一致の重複はスキップする。

        有効な事実が上限を超える場合は、一部だけ入れずに 409 で全体を拒否する。

        Append an import batch atomically and skip exact duplicates.
        """
        await self._lock_user_writes(user_id)

        def signature(fact: dict[str, Any]) -> tuple[str, str, str, str, int]:
            return (
                str(fact["fact_type"]),
                str(fact["title"]),
                str(fact["content"]),
                str(fact["status"]),
                int(fact["importance"]),
            )

        unique_facts: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str, int]] = set()
        skipped_duplicate_count = 0
        for fact in facts:
            item_signature = signature(fact)
            if item_signature in seen:
                skipped_duplicate_count += 1
                continue
            seen.add(item_signature)
            unique_facts.append(fact)

        existing_signatures = await self.find_existing_portable_signatures(
            user_id, unique_facts
        )
        skipped_duplicate_count += len(existing_signatures)
        importable = [fact for fact in unique_facts if signature(fact) not in existing_signatures]

        current_active = await self.count_active(user_id)
        active_to_insert = sum(1 for fact in importable if fact["status"] == "active")
        if current_active + active_to_insert > MAX_ACTIVE_CONTEXT_FACTS:
            raise ApiServiceError(ERROR_CONTEXT_FACT_LIMIT_REACHED, 409, status="fail")

        imported: list[dict[str, Any]] = []
        if importable:
            # last_confirmed_at / confidence は書かない: import は外部由来なので未確認（NULL）のまま。
            # Neither last_confirmed_at nor confidence is written: imports are external, so they stay unconfirmed (NULL).
            statement = pg_insert(ContextFact).values(
                [
                    {
                        "user_id": user_id,
                        "fact_type": fact["fact_type"],
                        "title": fact["title"],
                        "content": fact["content"],
                        "source_kind": "import",
                        "importance": fact["importance"],
                        "status": fact["status"],
                    }
                    for fact in importable
                ]
            ).returning(*_FACT_RETURNING_COLUMNS)
            rows = (await self.session.execute(statement)).mappings().all()
            imported = [self._serialize_row(row) for row in rows]

        return {
            "facts": imported,
            "skipped_duplicate_count": skipped_duplicate_count,
            "active_count": sum(1 for fact in imported if fact["status"] == "active"),
            "deprecated_count": sum(1 for fact in imported if fact["status"] == "deprecated"),
        }

    async def update_fact(
        self,
        user_id: int,
        fact_id: int,
        *,
        expected_revision: int,
        title: str | None = None,
        content: str | None = None,
        fact_type: str | None = None,
        status: str | None = None,
        importance: int | None = None,
        confirmed_by_owner: bool = False,
    ) -> dict[str, Any]:
        """revision による楽観ロックで事実を更新する。

        title・content・種類を実際に変えたときは、本人の操作なら last_confirmed_at を現在時刻にし、
        それ以外(MCP クライアントの書き換え)なら NULL に戻す。同じ値の再送、状態変更、重要度の変更では確認状態を変えない。

        Update a fact under optimistic locking.

        Changing title, content, or type sets ``last_confirmed_at`` to now when the owner
        made the change and clears it otherwise (an MCP client rewrote it and the owner has
        not seen it). Re-sending unchanged fields, status changes, and importance changes
        leave confirmation alone.
        """
        # 日本語: deprecated などから active に戻すときだけ、有効件数の上限を確認する(既に active なら件数は増えない)。
        # English: The active-count cap is checked only when reactivating a non-active fact, since an already-active fact adds no count.
        if status == "active":
            await self._lock_user_writes(user_id)
            current_status = await self.session.scalar(
                select(ContextFact.status).where(
                    ContextFact.id == fact_id,
                    ContextFact.user_id == user_id,
                )
            )
            if (
                current_status is not None
                and current_status != "active"
                and await self.count_active(user_id) >= MAX_ACTIVE_CONTEXT_FACTS
            ):
                raise ApiServiceError(ERROR_CONTEXT_FACT_LIMIT_REACHED, 409, status="fail")

        changes: dict[str, Any] = {"revision": ContextFact.revision + 1}
        content_change_conditions = []
        if title is not None:
            changes["title"] = title
            content_change_conditions.append(ContextFact.title.is_distinct_from(title))
        if content is not None:
            changes["content"] = content
            content_change_conditions.append(ContextFact.content.is_distinct_from(content))
        if fact_type is not None:
            changes["fact_type"] = fact_type
            content_change_conditions.append(ContextFact.fact_type.is_distinct_from(fact_type))
        # 日本語: 値が実際に変わった(IS DISTINCT FROM)ときだけ埋め込みを再生成待ちにし、確認時刻を更新する。
        # English: Only when a value actually changes (IS DISTINCT FROM) is the embedding marked pending and confirmation updated.
        if content_change_conditions:
            content_changed = or_(*content_change_conditions)
            changes["embedding_status"] = case(
                (content_changed, "pending"),
                else_=ContextFact.embedding_status,
            )
            changes["last_confirmed_at"] = case(
                (
                    content_changed,
                    func.current_timestamp() if confirmed_by_owner else null(),
                ),
                else_=ContextFact.last_confirmed_at,
            )
        if status is not None:
            changes["status"] = status
        if importance is not None:
            changes["importance"] = importance
        changes["updated_at"] = func.current_timestamp()

        statement = (
            update(ContextFact)
            .where(
                ContextFact.id == fact_id,
                ContextFact.user_id == user_id,
                ContextFact.revision == expected_revision,
            )
            .values(**changes)
            .returning(*_FACT_RETURNING_COLUMNS)
        )
        row = (await self.session.execute(statement)).mappings().first()
        if row is not None:
            return self._serialize_row(row)

        # 日本語: 更新が 0 行のとき、事実が無い(404)のか revision の不一致(409)なのかを区別する。
        # English: With zero rows updated, tell "fact not found" (404) apart from a revision mismatch (409).
        exists_for_owner = await self.session.scalar(
            select(exists().where(ContextFact.id == fact_id, ContextFact.user_id == user_id))
        )
        if not exists_for_owner:
            raise ResourceNotFoundError(ERROR_CONTEXT_FACT_NOT_FOUND)
        raise ApiServiceError(ERROR_CONTEXT_FACT_REVISION_CONFLICT, 409, status="fail")

    # 日本語: 埋め込みを保存して ready にする。expected_revision を渡すと、生成中に事実が更新されていた場合は古い埋め込みを書き込まない。
    # English: Stores the embedding and marks it ready; with expected_revision, a stale embedding is not
    # written if the fact changed meanwhile.
    async def store_embedding(
        self,
        fact_id: int,
        embedding: list[float],
        expected_revision: int | None = None,
    ) -> None:
        conditions = [ContextFact.id == fact_id]
        if expected_revision is not None:
            conditions.append(ContextFact.revision == expected_revision)
        statement = (
            update(ContextFact)
            .where(*conditions)
            .values(
                embedding_vector=[float(value) for value in embedding],
                embedding_status="ready",
            )
        )
        await self.session.execute(statement)
