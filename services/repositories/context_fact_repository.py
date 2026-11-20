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
    DateTime,
    and_,
    bindparam,
    case,
    cast,
    column,
    delete,
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
    ERROR_CONTEXT_MEMORY_USE_SETTINGS_NOT_FOUND,
)
from services.models import ContextFact, ContextFactSource, User
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
    "deprecated_reason",
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
        "deprecated_reason": str(record["deprecated_reason"]) if record["deprecated_reason"] is not None else None,
        "created_at": serialize_datetime_iso(record["created_at"]),
        "updated_at": serialize_datetime_iso(record["updated_at"]),
        "_updated_at_raw": record["updated_at"],
    }


# 日本語: 事実が最後に話題に出た時刻。出典 context_fact_sources.observed_at の最大値で、出典が無ければ updated_at。
# observed_at は timestamptz、updated_at はタイムゾーン無しなので、updated_at を timestamptz へ明示的に変換して揃える。
# 毎ターンのまとめと記憶の検索が同じ定義を使う。
# English: When a fact was last mentioned: the newest context_fact_sources.observed_at, or updated_at without a source. observed_at is
# timestamptz while updated_at is timezone-less, so updated_at is cast to timestamptz explicitly. The per-turn summary and memory search
# share this definition.
def _last_mentioned_at():
    return func.coalesce(
        select(func.max(ContextFactSource.observed_at)).where(ContextFactSource.fact_id == ContextFact.id).scalar_subquery(),
        cast(ContextFact.updated_at, DateTime(timezone=True)),
    ).label("last_mentioned_at")


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

    # 日本語: 列は NOT NULL なので None はユーザー行が読めなかったときだけ。その場合は「使わない」として扱い、
    # 読めない相手の記憶を回答へ入れない。初期オンは列の server_default（と migration）だけで表す。
    # English: The column is NOT NULL, so None only means the user row could not be read. That counts as "do not use",
    # so the memory of a user we cannot read never reaches an answer. On-by-default lives only in the column's server_default
    # (and the migration).
    async def get_memory_use_enabled(self, user_id: int) -> bool:
        enabled = await self.session.scalar(select(User.memory_use_enabled).where(User.id == user_id))
        return bool(enabled) if enabled is not None else False

    async def update_memory_use_enabled(self, user_id: int, enabled: bool) -> bool:
        result = await self.session.execute(
            update(User).where(User.id == user_id).values(memory_use_enabled=bool(enabled)).returning(User.memory_use_enabled)
        )
        value = result.scalar_one_or_none()
        if value is None:
            raise ResourceNotFoundError(ERROR_CONTEXT_MEMORY_USE_SETTINGS_NOT_FOUND)
        return bool(value)

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

    # 日本語: 毎ターン文脈へ入れる記憶のまとめ用に、有効で本人由来の事実を 1 回の読み取りで返す。
    # 本人由来とは、本人が確認した事実(last_confirmed_at が非 NULL)と、チャットから抽出した事実(source_kind が chat)。
    # MCP・取り込みで入って本人が確認していない事実は返さない(ADR 0025)。MCP 向けの list_active_for_digest とは別の問い合わせで、
    # 順序は重要度の高い順、同じなら最後に話題に出た(出典 context_fact_sources.observed_at の最大値、出典が無ければ updated_at)が新しい順、
    # それも同じなら id の大きい順。observed_at は timestamptz、updated_at はタイムゾーン無しなので、updated_at を timestamptz へ
    # 明示的に変換して揃える(候補リポジトリの入れ替え判定と同じ扱い)。
    # English: One read of the active, owner-originated facts for the per-turn memory summary. Owner-originated means confirmed by
    # the owner (last_confirmed_at is not NULL) or extracted from chat (source_kind is chat); unconfirmed facts that arrived through
    # MCP or import are not returned (ADR 0025). This is a separate query from list_active_for_digest, which serves MCP. Order:
    # importance descending, then the most recently mentioned (newest context_fact_sources.observed_at, or updated_at without a
    # source), then id descending. observed_at is timestamptz while updated_at is timezone-less, so updated_at is cast to
    # timestamptz explicitly, as the candidate repository does when it picks a fact to replace.
    async def list_owner_facts_for_memory_summary(self, user_id: int) -> list[dict[str, Any]]:
        last_mentioned = _last_mentioned_at()
        result = await self.session.execute(
            select(
                ContextFact.id,
                ContextFact.fact_type,
                ContextFact.title,
                ContextFact.content,
                ContextFact.importance,
                last_mentioned,
            )
            .where(
                ContextFact.user_id == user_id,
                ContextFact.status == "active",
                or_(ContextFact.last_confirmed_at.is_not(None), ContextFact.source_kind == "chat"),
            )
            .order_by(ContextFact.importance.desc(), last_mentioned.desc().nulls_last(), ContextFact.id.desc())
            .limit(MAX_ACTIVE_CONTEXT_FACTS)
        )
        return [dict(row) for row in result.mappings().all()]

    # 日本語: 記憶の検索の順位づけ用に、その利用者の有効な事実すべて(上限 MAX_ACTIVE_CONTEXT_FACTS)を 1 回の読み取りで返す。
    # embedding があれば、各行に検索語の埋め込みとのコサイン距離 distance を付ける(ベクトルがまだ無い行は None)。無ければ全行 None。
    # 順位づけ(services/memory_search_ranking.py)は Python 側で行うので、語の一致を DB で絞らない。MCP の search_context 用の
    # search_facts(semantic_search / text_search)とは別の問い合わせで、そちらの挙動は変えない。
    # English: All of the user's active facts (capped at MAX_ACTIVE_CONTEXT_FACTS) in one read for memory-search ranking. With an
    # embedding each row carries `distance`, its cosine distance to the query embedding (None for a row with no vector yet); without
    # one every row's distance is None. Ranking (services/memory_search_ranking.py) happens in Python, so word matches are not filtered
    # in the database. This is a separate query from search_facts (semantic_search / text_search) behind MCP search_context, whose
    # behavior is unchanged.
    async def list_active_for_memory_search(
        self,
        user_id: int,
        embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        distance = self._distance(embedding).label("distance") if embedding else null().label("distance")
        result = await self.session.execute(
            select(
                ContextFact.id,
                ContextFact.fact_type,
                ContextFact.title,
                ContextFact.content,
                ContextFact.importance,
                ContextFact.source_kind,
                ContextFact.last_confirmed_at,
                _last_mentioned_at(),
                distance,
            )
            .where(ContextFact.user_id == user_id, ContextFact.status == "active")
            .order_by(ContextFact.id.desc())
            .limit(MAX_ACTIVE_CONTEXT_FACTS)
        )
        return [dict(row) for row in result.mappings().all()]

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
        return ContextFact.embedding_vector.cosine_distance(query_vector)

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
        それ以外(MCP クライアントの書き換え)なら NULL に戻し、出所(source_kind)を mcp にする。同時に、その事実の出典
        (context_fact_sources)を同じトランザクションで消す(引用が新しい文面を裏づけなくなるため)。
        同じ値の再送、状態変更、重要度の変更では確認状態・出所・出典を変えない。

        Update a fact under optimistic locking.

        Changing title, content, or type sets ``last_confirmed_at`` to now when the owner
        made the change; otherwise (an MCP client rewrote it and the owner has not seen it) it is
        cleared and source_kind becomes mcp. Either way the fact's sources
        (context_fact_sources) are deleted in the same transaction, since the quotes no longer back the
        new wording. Re-sending unchanged fields, status changes, and importance changes
        leave confirmation, provenance and sources alone.
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
        content_will_change = False
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
            # 日本語: 更新の前に事実の行を FOR UPDATE でロックし、更新と同じ revision で「実際に変わるか」を判定する。
            # 出典の削除は更新の後（行ロックを持ったまま）に行うので、並行して出典を足す側（FOR SHARE で revision を確かめる）は
            # 更新後の事実には入れず、更新前に入れた出典はこの削除で消える。
            # English: The fact row is locked FOR UPDATE before the update, and the "actually changes" test runs under the
            # update's own revision. Sources are deleted after the update while the row lock is still held, so a concurrent
            # source writer (FOR SHARE, checking the revision) cannot add one to the updated fact, and one it added earlier is
            # removed by this delete.
            content_will_change = await self.session.scalar(
                select(content_changed)
                .where(
                    ContextFact.id == fact_id,
                    ContextFact.user_id == user_id,
                    ContextFact.revision == expected_revision,
                )
                .with_for_update()
            )
            if not confirmed_by_owner:
                changes["source_kind"] = case((content_changed, "mcp"), else_=ContextFact.source_kind)
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
        # 日本語: 利用者・MCP による無効化は理由 user、有効へ戻すときは NULL にする。上限での自動の入れ替え(capacity)は
        # 抽出の保存側(context_fact_candidate_repository)だけが書く。
        # English: Deprecating through the owner or MCP records reason user; restoring clears it. The automatic replacement at
        # the cap (capacity) is written only by the extraction store (context_fact_candidate_repository).
        if status is not None:
            changes["status"] = status
            changes["deprecated_reason"] = "user" if status == "deprecated" else None
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
            if content_will_change:
                await self.session.execute(delete(ContextFactSource).where(ContextFactSource.fact_id == fact_id))
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
