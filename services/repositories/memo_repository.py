"""Async SQLAlchemy repository for memo entries and collections."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any, TypeVar

from sqlalchemy import (
    Numeric,
    bindparam,
    case,
    cast,
    delete,
    exists,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.datetime_serialization import serialize_datetime_iso
from services.db import session_scope
from services.embeddings import get_semantic_max_distance
from services.models import MemoCollection, MemoEntry, SharedMemoEntry
from services.models.types import Vector
from services.search_terms import build_like_pattern, split_search_terms

from .memo_constants import COLLECTION_NOT_FOUND_ERROR, MEMO_NOT_FOUND_ERROR
from .memo_helpers import date_end, date_start, ensure_title
from .memo_serializers import serialize_memo_detail, serialize_memo_summary

T = TypeVar("T")


async def _in_transaction(
    session: AsyncSession | None,
    operation: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    """Run one repository operation in an isolated transaction when needed."""
    if session is not None:
        return await operation(session)
    async with session_scope() as owned_session:
        async with owned_session.begin():
            return await operation(owned_session)


def _row_dict(row: Any) -> dict[str, Any]:
    mapping = row if hasattr(row, "keys") else getattr(row, "_mapping", row)
    return dict(mapping)


def _summary_columns(*, detail: bool = False):
    response = MemoEntry.ai_response if detail else func.left(
        func.coalesce(MemoEntry.ai_response, ""), 400
    ).label("preview_response")
    return (
        MemoEntry.id.label("id"),
        MemoEntry.title.label("title"),
        response,
        MemoEntry.created_at.label("created_at"),
        MemoEntry.updated_at.label("updated_at"),
        MemoEntry.revision.label("revision"),
        MemoEntry.archived_at.label("archived_at"),
        MemoEntry.pinned_at.label("pinned_at"),
        MemoEntry.collection_id.label("collection_id"),
        MemoEntry.background_color.label("background_color"),
        MemoCollection.name.label("collection_name"),
        MemoCollection.color.label("collection_color"),
        SharedMemoEntry.share_token.label("share_token"),
        SharedMemoEntry.expires_at.label("expires_at"),
        SharedMemoEntry.revoked_at.label("revoked_at"),
    )


def _memo_from_row(row: Any, *, detail: bool) -> dict[str, Any]:
    payload = _row_dict(row)
    return serialize_memo_detail(payload) if detail else serialize_memo_summary(payload)


def _memo_from_detail_row(row: Any) -> dict[str, Any]:
    return _memo_from_row(row, detail=True)


def _memo_join_statement(*, detail: bool = False):
    return (
        select(*_summary_columns(detail=detail))
        .select_from(MemoEntry)
        .outerjoin(MemoCollection, MemoCollection.id == MemoEntry.collection_id)
        .outerjoin(SharedMemoEntry, SharedMemoEntry.memo_entry_id == MemoEntry.id)
    )


async def fetch_memo_summaries(
    user_id: int,
    *,
    limit: int,
    offset: int,
    query: str,
    date_from: str,
    date_to: str,
    sort: str,
    include_archived: bool,
    only_archived: bool,
    pinned_first: bool,
    collection_id: int | None,
    semantic_query_embedding: list[float] | None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    async def operation(db: AsyncSession) -> dict[str, Any]:
        conditions = [MemoEntry.user_id == user_id]
        if only_archived:
            conditions.append(MemoEntry.archived_at.is_not(None))
        elif not include_archived:
            conditions.append(MemoEntry.archived_at.is_(None))

        normalized_query = query.strip()
        if normalized_query and not semantic_query_embedding:
            for term in split_search_terms(normalized_query):
                pattern = build_like_pattern(term)
                conditions.append(
                    MemoEntry.title.ilike(pattern, escape="\\")
                    | MemoEntry.ai_response.ilike(pattern, escape="\\")
                )
        parsed_date_from = date_start(date_from)
        if parsed_date_from is not None:
            conditions.append(MemoEntry.created_at >= parsed_date_from)
        parsed_date_to = date_end(date_to)
        if parsed_date_to is not None:
            conditions.append(MemoEntry.created_at <= parsed_date_to)
        if collection_id is not None:
            conditions.append(MemoEntry.collection_id == collection_id)

        if semantic_query_embedding is not None:
            distance = _vector_distance(semantic_query_embedding)
            semantic_conditions = [
                *conditions,
                MemoEntry.embedding_vector.is_not(None),
                distance <= get_semantic_max_distance(),
            ]
            total = await db.scalar(
                select(func.count(MemoEntry.id)).where(*semantic_conditions)
            )
            statement = (
                _memo_join_statement()
                .where(*semantic_conditions)
                .order_by(distance)
                .limit(limit)
                .offset(offset)
            )
            rows = (await db.execute(statement)).mappings().all()
            return {
                "total": int(total or 0),
                "memos": [_memo_from_row(row, detail=False) for row in rows],
            }

        order_by = []
        if pinned_first:
            order_by.append(case((MemoEntry.pinned_at.is_(None), 1), else_=0).asc())
            if sort != "manual":
                order_by.append(MemoEntry.pinned_at.desc())
        sort_expression = _resolve_sort_expression(sort)
        if isinstance(sort_expression, tuple):
            order_by.extend(sort_expression)
        else:
            order_by.append(sort_expression)
        total = await db.scalar(select(func.count(MemoEntry.id)).where(*conditions))
        rows = (
            await db.execute(
                _memo_join_statement()
                .where(*conditions)
                .order_by(*order_by)
                .limit(limit)
                .offset(offset)
            )
        ).mappings().all()
        return {
            "total": int(total or 0),
            "memos": [_memo_from_row(row, detail=False) for row in rows],
        }

    return await _in_transaction(session, operation)


def _resolve_sort_expression(sort: str):
    if sort == "manual":
        return func.coalesce(
            MemoEntry.sort_order,
            cast(func.extract("epoch", MemoEntry.created_at), Numeric),
        ).desc().nulls_last()
    if sort == "oldest":
        return MemoEntry.created_at.asc()
    if sort == "updated":
        return MemoEntry.updated_at.desc()
    if sort == "title":
        return func.lower(MemoEntry.title).asc(), MemoEntry.created_at.desc()
    return MemoEntry.created_at.desc()


def _vector_distance(embedding: list[float]):
    return MemoEntry.embedding_vector.op("<=>")(
        bindparam(
            "memo_query_embedding",
            value=[float(value) for value in embedding],
            type_=Vector(768),
        )
    )


async def fetch_memo_detail(
    user_id: int,
    memo_id: int,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    async def operation(db: AsyncSession) -> dict[str, Any]:
        row = (
            await db.execute(
                _memo_join_statement(detail=True).where(
                    MemoEntry.id == memo_id,
                    MemoEntry.user_id == user_id,
                )
            )
        ).mappings().first()
        if row is None:
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
        return _memo_from_detail_row(row)

    return await _in_transaction(session, operation)


async def validate_collection_owner(
    session: AsyncSession,
    user_id: int,
    collection_id: int,
) -> bool:
    return (
        await session.scalar(
            select(MemoCollection.id).where(
                MemoCollection.id == collection_id,
                MemoCollection.user_id == user_id,
            )
        )
        is not None
    )


async def insert_memo(
    user_id: int,
    ai_response: str,
    resolved_title: str,
    collection_id: int | None,
    background_color: str | None = None,
    *,
    session: AsyncSession | None = None,
) -> int | None:
    async def operation(db: AsyncSession) -> int | None:
        validated_collection_id = None
        if collection_id is not None and await validate_collection_owner(
            db, user_id, collection_id
        ):
            validated_collection_id = collection_id
        max_order = await db.scalar(
            select(func.max(MemoEntry.sort_order)).where(MemoEntry.user_id == user_id)
        )
        statement = (
            insert(MemoEntry)
            .values(
                user_id=user_id,
                ai_response=ai_response,
                title=resolved_title,
                collection_id=validated_collection_id,
                background_color=background_color,
                sort_order=(max_order or Decimal("0")) + Decimal("1"),
            )
            .returning(MemoEntry.id)
        )
        return (await db.execute(statement)).scalar_one_or_none()

    return await _in_transaction(session, operation)


async def update_memo(
    user_id: int,
    memo_id: int,
    *,
    title: str | None,
    ai_response: str | None,
    collection_id: int | None,
    clear_collection: bool,
    background_color: str | None = None,
    clear_background_color: bool = False,
    expected_revision: int | None = None,
    allow_shared_content_change: bool = True,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    async def operation(db: AsyncSession) -> dict[str, Any]:
        existing = await db.execute(
            select(
                MemoEntry.title,
                MemoEntry.ai_response,
                MemoEntry.collection_id,
                MemoEntry.background_color,
                MemoEntry.revision,
                exists().where(
                    SharedMemoEntry.memo_entry_id == MemoEntry.id,
                    SharedMemoEntry.revoked_at.is_(None),
                    (SharedMemoEntry.expires_at.is_(None)
                     | (SharedMemoEntry.expires_at > func.current_timestamp())),
                ).label("is_shared"),
            ).where(MemoEntry.id == memo_id, MemoEntry.user_id == user_id)
        )
        current_row = existing.mappings().first()
        if current_row is None:
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
        current = dict(current_row)
        if expected_revision is not None and int(current["revision"] or 0) != expected_revision:
            raise ApiServiceError(
                "メモが別の操作で更新されています。再読み込みしてからやり直してください。",
                409,
                status="fail",
            )
        if not allow_shared_content_change and bool(current["is_shared"]):
            raise ApiServiceError(
                "共有中のメモを更新するには、公開内容の変更を明示的に許可してください。",
                409,
                status="fail",
            )

        resolved_content = ai_response if ai_response is not None else current["ai_response"] or ""
        if not str(resolved_content).strip():
            raise ApiServiceError("AIの回答を入力してください。", 400, status="fail")
        resolved_title = current["title"] or ""
        if title is not None:
            resolved_title = ensure_title(str(resolved_content), title)
        resolved_collection = current["collection_id"]
        if clear_collection:
            resolved_collection = None
        elif collection_id is not None and await validate_collection_owner(
            db, user_id, collection_id
        ):
            resolved_collection = collection_id
        if clear_background_color:
            resolved_background_color = None
        elif background_color is not None:
            resolved_background_color = background_color
        else:
            resolved_background_color = current["background_color"]

        conditions = [MemoEntry.id == memo_id, MemoEntry.user_id == user_id]
        if expected_revision is not None:
            conditions.append(MemoEntry.revision == expected_revision)
        if not allow_shared_content_change:
            conditions.append(
                ~exists().where(
                    SharedMemoEntry.memo_entry_id == MemoEntry.id,
                    SharedMemoEntry.revoked_at.is_(None),
                    (SharedMemoEntry.expires_at.is_(None)
                     | (SharedMemoEntry.expires_at > func.current_timestamp())),
                )
            )
        statement = (
            update(MemoEntry)
            .where(*conditions)
            .values(
                title=resolved_title,
                ai_response=resolved_content,
                collection_id=resolved_collection,
                background_color=resolved_background_color,
                revision=MemoEntry.revision + 1,
                updated_at=func.current_timestamp(),
                **(
                    {"embedding_status": "pending"}
                    if title is not None or ai_response is not None
                    else {}
                ),
            )
            .returning(MemoEntry.revision)
        )
        if (await db.execute(statement)).scalar_one_or_none() is None:
            if not await db.scalar(
                select(exists().where(MemoEntry.id == memo_id, MemoEntry.user_id == user_id))
            ):
                raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
            if not allow_shared_content_change and await db.scalar(
                select(exists().where(
                    SharedMemoEntry.memo_entry_id == memo_id,
                    SharedMemoEntry.revoked_at.is_(None),
                    (SharedMemoEntry.expires_at.is_(None)
                     | (SharedMemoEntry.expires_at > func.current_timestamp())),
                ))
            ):
                raise ApiServiceError(
                    "共有中のメモを更新するには、公開内容の変更を明示的に許可してください。",
                    409,
                    status="fail",
                )
            raise ApiServiceError(
                "メモが別の操作で更新されています。再読み込みしてからやり直してください。",
                409,
                status="fail",
            )
        return await fetch_memo_detail(user_id, memo_id, session=db)

    return await _in_transaction(session, operation)


async def set_memo_archive_state(
    user_id: int,
    memo_id: int,
    enabled: bool,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    async def operation(db: AsyncSession) -> dict[str, Any]:
        statement = (
            update(MemoEntry)
            .where(MemoEntry.id == memo_id, MemoEntry.user_id == user_id)
            .values(
                archived_at=func.current_timestamp() if enabled else None,
                revision=MemoEntry.revision + 1,
                updated_at=func.current_timestamp(),
            )
            .returning(MemoEntry.id)
        )
        if (await db.execute(statement)).scalar_one_or_none() is None:
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
        return await fetch_memo_detail(user_id, memo_id, session=db)

    return await _in_transaction(session, operation)


async def set_memo_pin_state(
    user_id: int,
    memo_id: int,
    enabled: bool,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    async def operation(db: AsyncSession) -> dict[str, Any]:
        values: dict[str, Any] = {
            "pinned_at": func.current_timestamp() if enabled else None,
            "revision": MemoEntry.revision + 1,
            "updated_at": func.current_timestamp(),
        }
        if enabled:
            values["sort_order"] = (
                select(func.coalesce(func.max(MemoEntry.sort_order), 0) + 1)
                .where(
                    MemoEntry.user_id == user_id,
                    MemoEntry.archived_at.is_(None),
                    MemoEntry.pinned_at.is_not(None),
                )
                .scalar_subquery()
            )
        statement = (
            update(MemoEntry)
            .where(MemoEntry.id == memo_id, MemoEntry.user_id == user_id)
            .values(**values)
            .returning(MemoEntry.id)
        )
        if (await db.execute(statement)).scalar_one_or_none() is None:
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
        return await fetch_memo_detail(user_id, memo_id, session=db)

    return await _in_transaction(session, operation)


def _decimal_order(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


async def reorder_memo(
    user_id: int,
    memo_id: int,
    *,
    before_id: int | None,
    after_id: int | None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    if before_id == memo_id or after_id == memo_id:
        raise ApiServiceError("並べ替え位置が不正です。", 400, status="fail")

    async def operation(db: AsyncSession) -> dict[str, Any]:
        ids = [memo_id] + [value for value in (before_id, after_id) if value is not None]
        ids = list(dict.fromkeys(ids))
        order_expression = func.coalesce(
            MemoEntry.sort_order,
            cast(func.extract("epoch", MemoEntry.created_at), Numeric),
        ).label("resolved_sort_order")
        rows = (
            await db.execute(
                select(
                    MemoEntry.id,
                    order_expression,
                    MemoEntry.pinned_at,
                    MemoEntry.archived_at,
                ).where(MemoEntry.user_id == user_id, MemoEntry.id.in_(ids))
            )
        ).mappings().all()
        by_id = {int(row["id"]): dict(row) for row in rows}
        dragged = by_id.get(memo_id)
        if dragged is None:
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
        dragged_pinned = dragged["pinned_at"] is not None
        dragged_archived = dragged["archived_at"] is not None

        def neighbor_order(neighbor_id: int | None) -> Decimal | None:
            if neighbor_id is None:
                return None
            neighbor = by_id.get(neighbor_id)
            if neighbor is None:
                raise ApiServiceError("並べ替え先のメモが見つかりません。", 400, status="fail")
            if (
                (neighbor["pinned_at"] is not None) != dragged_pinned
                or (neighbor["archived_at"] is not None) != dragged_archived
            ):
                raise ApiServiceError(
                    "ピン留めまたはアーカイブ状態が異なるメモの間には移動できません。",
                    400,
                    status="fail",
                )
            return _decimal_order(neighbor["resolved_sort_order"])

        before_order = neighbor_order(before_id)
        after_order = neighbor_order(after_id)
        if before_order is not None and after_order is not None:
            new_order = (before_order + after_order) / Decimal("2")
        elif before_order is not None:
            new_order = before_order - Decimal("1")
        elif after_order is not None:
            new_order = after_order + Decimal("1")
        else:
            next_order = await db.scalar(
                select(func.coalesce(func.max(MemoEntry.sort_order), 0) + 1).where(
                    MemoEntry.user_id == user_id,
                    (MemoEntry.pinned_at.is_not(None)) == dragged_pinned,
                    (MemoEntry.archived_at.is_not(None)) == dragged_archived,
                )
            )
            new_order = _decimal_order(next_order)

        statement = (
            update(MemoEntry)
            .where(MemoEntry.id == memo_id, MemoEntry.user_id == user_id)
            .values(
                sort_order=new_order,
                revision=MemoEntry.revision + 1,
                updated_at=func.current_timestamp(),
            )
            .returning(MemoEntry.id)
        )
        if (await db.execute(statement)).scalar_one_or_none() is None:
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)
        return await fetch_memo_detail(user_id, memo_id, session=db)

    return await _in_transaction(session, operation)


async def delete_memo(
    user_id: int,
    memo_id: int,
    *,
    session: AsyncSession | None = None,
) -> None:
    async def operation(db: AsyncSession) -> None:
        statement = delete(MemoEntry).where(
            MemoEntry.id == memo_id,
            MemoEntry.user_id == user_id,
        ).returning(MemoEntry.id)
        if (await db.execute(statement)).scalar_one_or_none() is None:
            raise ResourceNotFoundError(MEMO_NOT_FOUND_ERROR)

    await _in_transaction(session, operation)


async def bulk_action(
    user_id: int,
    action: str,
    memo_ids: list[int],
    *,
    collection_id: int | None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    if not memo_ids:
        return {"affected": 0}

    async def operation(db: AsyncSession) -> dict[str, Any]:
        owned_ids = (
            await db.scalars(
                select(MemoEntry.id).where(
                    MemoEntry.user_id == user_id,
                    MemoEntry.id.in_(memo_ids),
                )
            )
        ).all()
        if not owned_ids:
            return {"affected": 0}
        conditions = [MemoEntry.id.in_(owned_ids), MemoEntry.user_id == user_id]
        statement: Any
        if action == "delete":
            statement = delete(MemoEntry).where(*conditions).returning(MemoEntry.id)
        else:
            values: dict[str, Any] = {
                "revision": MemoEntry.revision + 1,
                "updated_at": func.current_timestamp(),
            }
            if action == "archive":
                values["archived_at"] = func.current_timestamp()
            elif action == "unarchive":
                values["archived_at"] = None
            elif action == "pin":
                values["pinned_at"] = func.current_timestamp()
            elif action == "unpin":
                values["pinned_at"] = None
            elif action == "set_collection" and collection_id is not None:
                if await validate_collection_owner(db, user_id, collection_id):
                    values["collection_id"] = collection_id
                else:
                    return {"affected": 0}
            elif action == "clear_collection":
                values["collection_id"] = None
            else:
                return {"affected": 0}
            statement = update(MemoEntry).where(*conditions).values(**values).returning(MemoEntry.id)
        affected = (await db.execute(statement)).scalars().all()
        return {"affected": len(affected)}

    return await _in_transaction(session, operation)


async def fetch_collections(
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    async def operation(db: AsyncSession) -> list[dict[str, Any]]:
        memo_count = func.count(MemoEntry.id).filter(MemoEntry.archived_at.is_(None))
        rows = (
            await db.execute(
                select(
                    MemoCollection.id,
                    MemoCollection.name,
                    MemoCollection.color,
                    MemoCollection.created_at,
                    MemoCollection.updated_at,
                    memo_count.label("memo_count"),
                )
                .outerjoin(MemoEntry, MemoEntry.collection_id == MemoCollection.id)
                .where(MemoCollection.user_id == user_id)
                .group_by(
                    MemoCollection.id,
                    MemoCollection.name,
                    MemoCollection.color,
                    MemoCollection.created_at,
                    MemoCollection.updated_at,
                )
                .order_by(MemoCollection.created_at.desc())
            )
        ).mappings().all()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "color": row["color"],
                "memo_count": int(row["memo_count"] or 0),
                "created_at": serialize_datetime_iso(row["created_at"]),
                "updated_at": serialize_datetime_iso(row["updated_at"]),
            }
            for row in rows
        ]

    return await _in_transaction(session, operation)


async def insert_collection(
    user_id: int,
    name: str,
    color: str,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    async def operation(db: AsyncSession) -> dict[str, Any]:
        statement = (
            insert(MemoCollection)
            .values(user_id=user_id, name=name.strip(), color=color.strip())
            .returning(
                MemoCollection.id,
                MemoCollection.name,
                MemoCollection.color,
                MemoCollection.created_at,
                MemoCollection.updated_at,
            )
        )
        row = (await db.execute(statement)).mappings().first()
        if row is None:
            raise RuntimeError("Insert did not return a row.")
        return {
            "id": row["id"],
            "name": row["name"],
            "color": row["color"],
            "memo_count": 0,
            "created_at": serialize_datetime_iso(row["created_at"]),
            "updated_at": serialize_datetime_iso(row["updated_at"]),
        }

    return await _in_transaction(session, operation)


async def update_collection(
    user_id: int,
    collection_id: int,
    name: str | None,
    color: str | None,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    async def operation(db: AsyncSession) -> dict[str, Any]:
        current = await db.execute(
            select(MemoCollection.name, MemoCollection.color).where(
                MemoCollection.id == collection_id,
                MemoCollection.user_id == user_id,
            )
        )
        existing = current.mappings().first()
        if existing is None:
            raise ResourceNotFoundError(COLLECTION_NOT_FOUND_ERROR)
        statement = (
            update(MemoCollection)
            .where(MemoCollection.id == collection_id, MemoCollection.user_id == user_id)
            .values(
                name=name.strip() if name is not None else existing["name"],
                color=color.strip() if color is not None else existing["color"],
                updated_at=func.current_timestamp(),
            )
            .returning(
                MemoCollection.id,
                MemoCollection.name,
                MemoCollection.color,
                MemoCollection.created_at,
                MemoCollection.updated_at,
            )
        )
        row = (await db.execute(statement)).mappings().first()
        if row is None:
            raise ResourceNotFoundError(COLLECTION_NOT_FOUND_ERROR)
        count = await db.scalar(
            select(func.count(MemoEntry.id)).where(
                MemoEntry.collection_id == collection_id,
                MemoEntry.archived_at.is_(None),
            )
        )
        return {
            "id": row["id"],
            "name": row["name"],
            "color": row["color"],
            "memo_count": int(count or 0),
            "created_at": serialize_datetime_iso(row["created_at"]),
            "updated_at": serialize_datetime_iso(row["updated_at"]),
        }

    return await _in_transaction(session, operation)


async def delete_collection(
    user_id: int,
    collection_id: int,
    *,
    session: AsyncSession | None = None,
) -> None:
    async def operation(db: AsyncSession) -> None:
        await db.execute(
            update(MemoEntry)
            .where(MemoEntry.collection_id == collection_id, MemoEntry.user_id == user_id)
            .values(
                collection_id=None,
                revision=MemoEntry.revision + 1,
                updated_at=func.current_timestamp(),
            )
        )
        statement = delete(MemoCollection).where(
            MemoCollection.id == collection_id,
            MemoCollection.user_id == user_id,
        ).returning(MemoCollection.id)
        if (await db.execute(statement)).scalar_one_or_none() is None:
            raise ResourceNotFoundError(COLLECTION_NOT_FOUND_ERROR)

    await _in_transaction(session, operation)
