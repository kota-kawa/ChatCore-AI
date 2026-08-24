"""Async SQLAlchemy persistence for the personal context vault."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import (
    and_,
    bindparam,
    column,
    exists,
    func,
    literal,
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

MAX_ACTIVE_CONTEXT_FACTS = 200
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
        "created_at": serialize_datetime_iso(record["created_at"]),
        "updated_at": serialize_datetime_iso(record["updated_at"]),
        "_updated_at_raw": record["updated_at"],
    }


class ContextFactRepository:
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

    @staticmethod
    def _distance(embedding: list[float]):
        query_vector = bindparam(
            "context_query_embedding",
            value=[float(value) for value in embedding],
            type_=Vector(768),
        )
        return ContextFact.embedding_vector.op("<=>")(query_vector)

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
            )
            .on_conflict_do_nothing(index_elements=[ContextFact.idempotency_key_hash])
            .returning(*_FACT_RETURNING_COLUMNS)
        )
        row = (await self.session.execute(statement)).mappings().first()
        if row is not None:
            return self._serialize_row(row)

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
        """Append an import batch atomically and skip exact duplicates."""
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
    ) -> dict[str, Any]:
        if status == "active":
            await self._lock_user_writes(user_id)
            current_status = await self.session.scalar(
                select(ContextFact.status).where(
                    ContextFact.id == fact_id,
                    ContextFact.user_id == user_id,
                )
            )
            if current_status is not None and current_status != "active":
                if await self.count_active(user_id) >= MAX_ACTIVE_CONTEXT_FACTS:
                    raise ApiServiceError(ERROR_CONTEXT_FACT_LIMIT_REACHED, 409, status="fail")

        changes: dict[str, Any] = {"revision": ContextFact.revision + 1}
        if title is not None:
            changes["title"] = title
        if content is not None:
            changes["content"] = content
        if fact_type is not None:
            changes["fact_type"] = fact_type
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

        exists_for_owner = await self.session.scalar(
            select(exists().where(ContextFact.id == fact_id, ContextFact.user_id == user_id))
        )
        if not exists_for_owner:
            raise ResourceNotFoundError(ERROR_CONTEXT_FACT_NOT_FOUND)
        raise ApiServiceError(ERROR_CONTEXT_FACT_REVISION_CONFLICT, 409, status="fail")

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
            .values(embedding_vector=[float(value) for value in embedding])
        )
        await self.session.execute(statement)
