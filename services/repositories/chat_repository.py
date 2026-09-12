"""Async SQLAlchemy persistence boundary for chat-owned data."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, func, literal, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.attached_files import decode_attached_files_from_storage, encode_attached_files_for_storage
from services.datetime_serialization import serialize_datetime_iso
from services.error_messages import (
    ERROR_CHAT_ROOM_DELETE_FORBIDDEN,
    ERROR_CHAT_ROOM_NOT_FOUND,
    ERROR_CHAT_ROOM_SHARE_FORBIDDEN,
    ERROR_SHARED_LINK_NOT_FOUND,
)
from services.generative_ui import decode_message_parts, encode_message_parts
from services.models import (
    ChatHistory,
    ChatRoom,
    ChatRoomSummary,
    MemoryFact,
    SharedChatRoom,
)
from services.repositories.chat_room_access import load_owned_room, serialize_room
from services.share_common import (
    SHARED_TOKEN_MAX_COLLISION_RETRIES,
    SHARED_TOKEN_RETRY_BACKOFF_SECONDS,
    TokenShareLifecycle,
    generate_share_token,
    is_unique_violation,
)

DB_WRITE_MAX_ATTEMPTS = 3
# Keep the old repository-level name for callers that imported it while using
# the shared share-token retry configuration as the single source of truth.
DB_RETRY_BACKOFF_SECONDS = SHARED_TOKEN_RETRY_BACKOFF_SECONDS


def _decode_web_search_context(raw: Any) -> list[dict[str, Any]] | None:
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            return None
    if not isinstance(raw, list):
        return None
    return [item for item in raw if isinstance(item, dict)] or None


def _jsonb_value(encoded: str | None) -> Any:
    if encoded is None:
        return None
    try:
        return json.loads(encoded)
    except (TypeError, json.JSONDecodeError):
        return encoded


def _is_unique_violation(exc: BaseException) -> bool:
    return is_unique_violation(exc)


# 日本語: ルームツリーの SELECT で取る列。attached_file_contents / message_parts /
#         web_search_context は JSONB に添付ファイル本文がそのまま入るため、本文が要らない
#         経路（リーフ判定・枝の走査）では読み出さない。
# English: Column projections for the room-tree SELECT. attached_file_contents, message_parts and
#          web_search_context are JSONB blobs that carry whole uploaded files, so paths that only
#          need to walk the branch (leaf lookup, deletion scan) never transfer them.
_TREE_NAVIGATION_COLUMNS: tuple[Any, ...] = (
    ChatHistory.id,
    ChatHistory.parent_id,
    ChatHistory.active_child_id,
)
_TREE_SENDER_COLUMNS: tuple[Any, ...] = (ChatHistory.sender,)
_TREE_WEB_SEARCH_COLUMNS: tuple[Any, ...] = (ChatHistory.web_search_context,)
_TREE_LLM_HISTORY_COLUMNS: tuple[Any, ...] = (
    ChatHistory.message,
    ChatHistory.sender,
    ChatHistory.message_parts,
    ChatHistory.attached_file_contents,
)
_TREE_DISPLAY_COLUMNS: tuple[Any, ...] = (
    ChatHistory.message,
    ChatHistory.sender,
    ChatHistory.timestamp,
    ChatHistory.attached_file_names,
    ChatHistory.message_parts,
)
_TREE_DISPLAY_WITH_ATTACHMENTS_COLUMNS: tuple[Any, ...] = (
    *_TREE_DISPLAY_COLUMNS,
    ChatHistory.attached_file_contents,
)
_TREE_SHARED_PAYLOAD_COLUMNS: tuple[Any, ...] = (
    ChatHistory.message,
    ChatHistory.sender,
    ChatHistory.timestamp,
    ChatHistory.message_parts,
)


class ChatRepository:
    """Repository for chat rooms, message history, branches, sharing and room memory.

    The repository never commits.  Services own the transaction and pass an
    isolated ``AsyncSession`` for one unit of work.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        token_generator: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        self.session = session
        self._token_generator = token_generator

    # Chat rooms and history -------------------------------------------------

    async def save_message(
        self,
        chat_room_id: str,
        message: str,
        sender: str,
        attached_file_names: list[str] | None = None,
        parent_id: int | None = None,
        message_parts: list[dict[str, Any]] | None = None,
        attached_file_contents: list[Any] | None = None,
        web_search_context: list[dict[str, Any]] | None = None,
    ) -> int | None:
        if parent_id is None:
            room = (
                await self.session.execute(
                    select(ChatRoom).where(ChatRoom.id == chat_room_id).with_for_update()
                )
            ).scalar_one_or_none()
            if room is None:
                raise ResourceNotFoundError(ERROR_CHAT_ROOM_NOT_FOUND)
        else:
            parent = (
                await self.session.execute(
                    select(ChatHistory)
                    .where(ChatHistory.id == parent_id, ChatHistory.chat_room_id == chat_room_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if parent is None:
                raise ResourceNotFoundError(ERROR_CHAT_ROOM_NOT_FOUND)

        record = ChatHistory(
            chat_room_id=chat_room_id,
            message=message,
            sender=sender,
            attached_file_names=(
                json.dumps(attached_file_names, ensure_ascii=False) if attached_file_names else None
            ),
            parent_id=parent_id,
            message_parts=_jsonb_value(encode_message_parts(message_parts)),
            attached_file_contents=_jsonb_value(encode_attached_files_for_storage(attached_file_contents)),
            web_search_context=_jsonb_value(
                json.dumps(web_search_context, ensure_ascii=False) if web_search_context else None
            ),
        )
        self.session.add(record)
        await self.session.flush()
        room_updates: dict[str, Any] = {"last_activity_at": func.current_timestamp()}
        if parent_id is None:
            room_updates["active_root_id"] = record.id
            await self.session.execute(update(ChatRoom).where(ChatRoom.id == chat_room_id).values(**room_updates))
        else:
            await self.session.execute(
                update(ChatHistory)
                .where(ChatHistory.id == parent_id, ChatHistory.chat_room_id == chat_room_id)
                .values(active_child_id=record.id)
            )
            await self.session.execute(update(ChatRoom).where(ChatRoom.id == chat_room_id).values(**room_updates))
        return record.id

    async def copy_messages_into_room(self, chat_room_id: str, messages: list[dict[str, Any]]) -> int:
        parent_id: int | None = None
        copied = 0
        for message in messages:
            if not isinstance(message, dict):
                continue
            new_id = await self.save_message(
                chat_room_id,
                str(message.get("message") or ""),
                "user" if message.get("sender") == "user" else "assistant",
                parent_id=parent_id,
                message_parts=(message.get("message_parts") if isinstance(message.get("message_parts"), list) else None),
            )
            if new_id is None:
                break
            parent_id = new_id
            copied += 1
        return copied

    async def create_room(self, room_id: str, user_id: int, title: str, mode: str = "normal") -> None:
        self.session.add(ChatRoom(id=room_id, user_id=user_id, title=title, mode=mode))
        await self.session.flush()

    async def list_user_rooms(
        self,
        user_id: int,
        *,
        limit: int | None = None,
        cursor: tuple[datetime, str] | None = None,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(ChatRoom)
            .where(ChatRoom.user_id == user_id, or_(ChatRoom.mode.is_(None), ChatRoom.mode != "temporary"))
            .order_by(ChatRoom.last_activity_at.desc(), ChatRoom.id.desc())
        )
        if cursor is not None:
            stmt = stmt.where(
                or_(
                    ChatRoom.last_activity_at < cursor[0],
                    and_(ChatRoom.last_activity_at == cursor[0], ChatRoom.id < cursor[1]),
                )
            )
        if limit is not None:
            stmt = stmt.limit(limit)
        return [serialize_room(room) for room in (await self.session.execute(stmt)).scalars().all()]

    async def delete_room_for_user(self, room_id: str, user_id: int) -> dict[str, str]:
        room = await load_owned_room(self.session, room_id, user_id, ERROR_CHAT_ROOM_DELETE_FORBIDDEN, lock=True)
        await self.session.execute(delete(ChatRoom).where(ChatRoom.id == room.id))
        return {"message": "削除しました"}

    async def delete_rooms_for_user(self, room_ids: list[str], user_id: int) -> dict[str, Any]:
        unique_room_ids = list(dict.fromkeys(room_ids))
        if not unique_room_ids:
            return {"message": "削除しました", "deleted_count": 0, "deleted_room_ids": []}
        rows = (
            await self.session.execute(
                select(ChatRoom.id, ChatRoom.user_id)
                .where(ChatRoom.id.in_(unique_room_ids))
                .with_for_update()
            )
        ).all()
        found = {str(room_id): owner_id for room_id, owner_id in rows}
        if len(found) != len(unique_room_ids):
            raise ResourceNotFoundError(ERROR_CHAT_ROOM_NOT_FOUND)
        if any(owner_id != user_id for owner_id in found.values()):
            raise ForbiddenOperationError("他ユーザーのチャットルームは削除できません")
        await self.session.execute(delete(ChatRoom).where(ChatRoom.id.in_(unique_room_ids)))
        return {"message": "削除しました", "deleted_count": len(unique_room_ids), "deleted_room_ids": unique_room_ids}

    async def delete_unanswered_user_messages(self, room_id: str, user_id: int) -> bool:
        room = await load_owned_room(self.session, room_id, user_id, "", lock=True, forbidden_returns_false=True)
        if room is None:
            return False
        nodes, active_root_id = await self._load_room_tree(room_id, columns=_TREE_SENDER_COLUMNS)
        children = self._children_by_parent(nodes)
        path = self._walk_active_path(nodes, active_root_id, children)
        removable_ids = self._trailing_unanswered_user_ids(path, children)
        if not removable_ids:
            return False
        first_removed = nodes[removable_ids[0]]
        if first_removed["parent_id"] is None:
            await self.session.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(active_root_id=None))
        else:
            await self.session.execute(
                update(ChatHistory)
                .where(ChatHistory.id == first_removed["parent_id"], ChatHistory.chat_room_id == room_id)
                .values(active_child_id=None)
            )
        result = await self.session.execute(
            delete(ChatHistory).where(ChatHistory.chat_room_id == room_id, ChatHistory.id.in_(removable_ids))
        )
        return bool(result.rowcount)

    async def rename_room(self, room_id: str, new_title: str) -> None:
        await self.session.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(title=new_title))

    async def rename_room_if_current_title_in(
        self, room_id: str, new_title: str, allowed_current_titles: list[str]
    ) -> bool:
        titles = [title for title in dict.fromkeys(allowed_current_titles) if title]
        if not titles:
            return False
        result = await self.session.execute(
            update(ChatRoom).where(ChatRoom.id == room_id, ChatRoom.title.in_(titles)).values(title=new_title)
        )
        return bool(result.rowcount)

    async def get_active_path(self, chat_room_id: str, *, include_attachment_contents: bool = False) -> list[dict[str, Any]]:
        columns = _TREE_DISPLAY_WITH_ATTACHMENTS_COLUMNS if include_attachment_contents else _TREE_DISPLAY_COLUMNS
        nodes, active_root_id = await self._load_room_tree(chat_room_id, columns=columns)
        children = self._children_by_parent(nodes)
        path = self._walk_active_path(nodes, active_root_id, children)
        return [
            self._serialize_path_node(node, children, include_attachment_contents=include_attachment_contents)
            for node in path
        ]

    async def get_active_leaf_id(self, chat_room_id: str) -> int | None:
        # 枝の末尾を知るだけなので、本文や添付 JSONB は一切読まない。
        # Only the branch tip is needed here, so no message body or JSONB blob is transferred.
        nodes, active_root_id = await self._load_room_tree(chat_room_id)
        path = self._walk_active_path(nodes, active_root_id, self._children_by_parent(nodes))
        return path[-1]["id"] if path else None

    async def switch_branch(self, chat_room_id: str, target_id: int) -> list[dict[str, Any]]:
        target = (
            await self.session.execute(
                select(ChatHistory)
                .where(ChatHistory.id == target_id, ChatHistory.chat_room_id == chat_room_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if target is None:
            raise ResourceNotFoundError(ERROR_CHAT_ROOM_NOT_FOUND)
        if target.parent_id is None:
            await self.session.execute(update(ChatRoom).where(ChatRoom.id == chat_room_id).values(active_root_id=target_id))
        else:
            await self.session.execute(
                update(ChatHistory)
                .where(ChatHistory.id == target.parent_id, ChatHistory.chat_room_id == chat_room_id)
                .values(active_child_id=target_id)
            )
        await self.session.flush()
        return await self.get_active_path(chat_room_id)

    async def get_room_messages_for_llm(self, chat_room_id: str) -> list[dict[str, Any]]:
        nodes, active_root_id = await self._load_room_tree(chat_room_id, columns=_TREE_LLM_HISTORY_COLUMNS)
        path = self._walk_active_path(nodes, active_root_id, self._children_by_parent(nodes))
        return self._path_to_llm_messages(path)

    async def get_active_path_web_search_contexts(self, chat_room_id: str) -> list[dict[str, Any]]:
        nodes, active_root_id = await self._load_room_tree(chat_room_id, columns=_TREE_WEB_SEARCH_COLUMNS)
        path = self._walk_active_path(nodes, active_root_id, self._children_by_parent(nodes))
        return self._path_to_web_search_contexts(path)

    async def validate_room_owner(self, room_id: str, user_id: int, forbidden_message: str) -> str | None:
        row = (
            await self.session.execute(
                select(ChatRoom.user_id, func.coalesce(ChatRoom.mode, literal("normal"))).where(ChatRoom.id == room_id)
            )
        ).one_or_none()
        if row is None:
            raise ResourceNotFoundError(ERROR_CHAT_ROOM_NOT_FOUND)
        if row[0] != user_id:
            raise ForbiddenOperationError(forbidden_message)
        return str(row[1] or "normal")

    async def _load_share_row(self, room_id: str) -> dict[str, Any] | None:
        """Read the share-link lifecycle row owned by ``room_id``."""

        result = await self.session.execute(
            select(
                SharedChatRoom.share_token,
                SharedChatRoom.expires_at,
                SharedChatRoom.revoked_at,
            ).where(SharedChatRoom.chat_room_id == room_id)
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    @staticmethod
    def _is_active_share(row: dict[str, Any]) -> bool:
        return TokenShareLifecycle(
            row.get("share_token"),
            row.get("expires_at"),
            row.get("revoked_at"),
        ).is_active

    async def create_or_get_shared_chat_token(
        self,
        room_id: str,
        user_id: int,
        *,
        expires_at: datetime | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Return the active share link for a room, minting a new token when needed.

        A revoked or expired row is replaced by a fresh token instead of being
        resurrected, so revoking a link can never be undone by re-opening the
        share dialog.
        """

        await load_owned_room(self.session, room_id, user_id, ERROR_CHAT_ROOM_SHARE_FORBIDDEN)
        if not force_refresh:
            existing = await self._load_share_row(room_id)
            if existing is not None and self._is_active_share(existing):
                return {**existing, "is_reused": True}
        for _ in range(SHARED_TOKEN_MAX_COLLISION_RETRIES):
            token = generate_share_token(self._token_generator)
            statement = (
                pg_insert(SharedChatRoom)
                .values(
                    chat_room_id=room_id,
                    share_token=token,
                    expires_at=expires_at,
                    revoked_at=None,
                )
                .on_conflict_do_update(
                    index_elements=[SharedChatRoom.chat_room_id],
                    set_={
                        "share_token": token,
                        "expires_at": expires_at,
                        "revoked_at": None,
                        "created_at": func.current_timestamp(),
                    },
                )
                .returning(
                    SharedChatRoom.share_token,
                    SharedChatRoom.expires_at,
                    SharedChatRoom.revoked_at,
                )
            )
            try:
                # A collision must roll back only this insert attempt.  The
                # caller may have other writes in the surrounding service
                # transaction, so rolling back the whole AsyncSession here
                # would silently discard unrelated work.
                async with self.session.begin_nested():
                    row = (await self.session.execute(statement)).mappings().first()
                if row is None:  # pragma: no cover - PostgreSQL RETURNING invariant
                    return {"share_token": token, "expires_at": expires_at, "revoked_at": None, "is_reused": False}
                return {**dict(row), "is_reused": False}
            except IntegrityError as exc:
                if not _is_unique_violation(exc):
                    raise
                await asyncio.sleep(DB_RETRY_BACKOFF_SECONDS)
                await load_owned_room(self.session, room_id, user_id, ERROR_CHAT_ROOM_SHARE_FORBIDDEN)
        raise RuntimeError("Failed to create shared chat token after collision retries.")

    async def revoke_shared_chat_token(self, room_id: str, user_id: int) -> dict[str, Any] | None:
        """Revoke the room's share link and return its resulting lifecycle state.

        ``None`` means the room never had a share link.  Re-revoking keeps the
        first ``revoked_at`` so audit trails stay truthful.
        """

        await load_owned_room(self.session, room_id, user_id, ERROR_CHAT_ROOM_SHARE_FORBIDDEN)
        result = await self.session.execute(
            update(SharedChatRoom)
            .where(
                SharedChatRoom.chat_room_id == room_id,
                SharedChatRoom.revoked_at.is_(None),
            )
            .values(revoked_at=func.current_timestamp())
            .returning(
                SharedChatRoom.share_token,
                SharedChatRoom.expires_at,
                SharedChatRoom.revoked_at,
            )
        )
        row = result.mappings().first()
        if row is not None:
            return dict(row)
        return await self._load_share_row(room_id)

    async def get_shared_chat_room_payload(self, token: str) -> dict[str, Any]:
        row = (
            await self.session.execute(
                select(ChatRoom.id, ChatRoom.title, ChatRoom.created_at)
                .join(SharedChatRoom, SharedChatRoom.chat_room_id == ChatRoom.id)
                .where(
                    SharedChatRoom.share_token == token,
                    SharedChatRoom.revoked_at.is_(None),
                    (
                        SharedChatRoom.expires_at.is_(None)
                        | (SharedChatRoom.expires_at > func.current_timestamp())
                    ),
                )
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            raise ResourceNotFoundError(ERROR_SHARED_LINK_NOT_FOUND)
        room_id, title, created_at = row
        nodes, active_root_id = await self._load_room_tree(room_id, columns=_TREE_SHARED_PAYLOAD_COLUMNS)
        path = self._walk_active_path(nodes, active_root_id, self._children_by_parent(nodes))
        messages: list[dict[str, Any]] = []
        for node in path:
            entry: dict[str, Any] = {
                "message": node["message"],
                "sender": node["sender"],
                "timestamp": serialize_datetime_iso(node["timestamp"]),
            }
            parts = decode_message_parts(node.get("message_parts"))
            if parts:
                entry["message_parts"] = parts
            messages.append(entry)
        return {
            "room": {"id": room_id, "title": title, "created_at": serialize_datetime_iso(created_at)},
            "messages": messages,
        }

    async def fetch_chat_history_page(
        self, chat_room_id: str, limit: int, before_message_id: int | None = None
    ) -> dict[str, Any]:
        nodes, active_root_id = await self._load_room_tree(chat_room_id, columns=_TREE_DISPLAY_COLUMNS)
        children = self._children_by_parent(nodes)
        path = self._walk_active_path(nodes, active_root_id, children)
        if before_message_id is not None:
            path = [node for node in path if node["id"] < before_message_id]
        has_more = len(path) > limit
        page_nodes = path[-limit:] if limit > 0 else []
        messages = [self._serialize_path_node(node, children) for node in page_nodes]
        return {
            "messages": messages,
            "pagination": {
                "limit": limit,
                "has_more": has_more,
                "next_before_id": messages[0]["id"] if has_more and messages else None,
            },
        }

    # Memory facts and summaries -------------------------------------------

    async def list_room_memory_facts(self, chat_room_id: str, *, limit: int = 8) -> list[str]:
        rows = (
            await self.session.execute(
                select(MemoryFact.fact)
                .where(
                    MemoryFact.chat_room_id == chat_room_id,
                    MemoryFact.scope == "room",
                    MemoryFact.is_active.is_(True),
                )
                .order_by(MemoryFact.updated_at.desc(), MemoryFact.id.desc())
                .limit(limit)
            )
        ).all()
        return [str(fact) for (fact,) in rows if fact]

    async def remember_facts(
        self,
        chat_room_id: str,
        user_id: int,
        facts: list[str],
        *,
        source_message_id: int | None = None,
    ) -> None:
        for fact in facts:
            existing = (
                await self.session.execute(
                    select(MemoryFact)
                    .where(
                        MemoryFact.chat_room_id == chat_room_id,
                        MemoryFact.scope == "room",
                        func.lower(MemoryFact.fact) == func.lower(fact),
                    )
                    .limit(1)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.fact = fact
                existing.user_id = user_id
                if source_message_id is not None:
                    existing.source_message_id = source_message_id
                existing.is_active = True
                existing.updated_at = datetime.utcnow()
            else:
                self.session.add(
                    MemoryFact(
                        user_id=user_id,
                        chat_room_id=chat_room_id,
                        scope="room",
                        fact=fact,
                        source_message_id=source_message_id,
                        is_active=True,
                    )
                )
        await self.session.flush()

    async def get_room_summary(self, chat_room_id: str) -> dict[str, Any] | None:
        summary = (
            await self.session.execute(select(ChatRoomSummary).where(ChatRoomSummary.chat_room_id == chat_room_id))
        ).scalar_one_or_none()
        if summary is None:
            return None
        return {
            "summary": summary.summary or "",
            "archived_message_count": int(summary.archived_message_count or 0),
            "updated_at": serialize_datetime_iso(summary.updated_at),
        }

    async def rebuild_room_summary(self, chat_room_id: str, summary: str, archived_count: int) -> str:
        if not summary:
            await self.session.execute(delete(ChatRoomSummary).where(ChatRoomSummary.chat_room_id == chat_room_id))
            return ""
        statement = (
            pg_insert(ChatRoomSummary)
            .values(chat_room_id=chat_room_id, summary=summary, archived_message_count=archived_count)
            .on_conflict_do_update(
                index_elements=[ChatRoomSummary.chat_room_id],
                set_={
                    "summary": summary,
                    "archived_message_count": archived_count,
                    "updated_at": text("CURRENT_TIMESTAMP"),
                },
            )
        )
        await self.session.execute(statement)
        return summary

    # Internal helpers -------------------------------------------------------

    async def _load_room_tree(
        self,
        chat_room_id: str,
        *,
        columns: tuple[Any, ...] = (),
    ) -> tuple[dict[int, dict[str, Any]], int | None]:
        """Load one room's message tree, transferring only the columns the caller reads.

        ``columns`` extends the navigation projection (``id`` / ``parent_id`` /
        ``active_child_id``).  Leaving it empty keeps whole uploaded files out of
        the result set for callers that only need to walk the branch.
        """

        rows = (
            await self.session.execute(
                select(*_TREE_NAVIGATION_COLUMNS, *columns)
                .where(ChatHistory.chat_room_id == chat_room_id)
                .order_by(ChatHistory.id)
            )
        ).mappings().all()
        nodes: dict[int, dict[str, Any]] = {int(row["id"]): dict(row) for row in rows}
        active_root_id = await self.session.scalar(select(ChatRoom.active_root_id).where(ChatRoom.id == chat_room_id))
        return nodes, active_root_id

    @staticmethod
    def _path_to_llm_messages(path: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Turn an active-branch path into the message list handed to the LLM."""

        messages: list[dict[str, Any]] = []
        for node in path:
            message: dict[str, Any] = {
                "role": "user" if node["sender"] == "user" else "assistant",
                "content": node["message"],
            }
            parts = decode_message_parts(node.get("message_parts"))
            if parts:
                message["message_parts"] = parts
            attached = decode_attached_files_from_storage(node.get("attached_file_contents"))
            if attached:
                message["attached_file_contents"] = [{"name": item.name, "content": item.content} for item in attached]
            messages.append(message)
        return messages

    @staticmethod
    def _path_to_web_search_contexts(path: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collect the web-search evidence stored along an active-branch path."""

        contexts: list[dict[str, Any]] = []
        for node in path:
            decoded = _decode_web_search_context(node.get("web_search_context"))
            if decoded:
                contexts.extend(decoded)
        return contexts

    @staticmethod
    def _trailing_unanswered_user_ids(path: list[dict[str, Any]], children: dict[int | None, list[int]]) -> list[int]:
        removable: set[int] = set()
        for node in reversed(path):
            if node["sender"] != "user":
                break
            if any(child_id not in removable for child_id in children.get(node["id"], [])):
                break
            removable.add(node["id"])
        return [node["id"] for node in path if node["id"] in removable]

    @staticmethod
    def _children_by_parent(nodes: dict[int, dict[str, Any]]) -> dict[int | None, list[int]]:
        children: dict[int | None, list[int]] = defaultdict(list)
        for node in nodes.values():
            children[node["parent_id"]].append(node["id"])
        for sibling_ids in children.values():
            sibling_ids.sort()
        return children

    @staticmethod
    def _walk_active_path(
        nodes: dict[int, dict[str, Any]], active_root_id: int | None, children: dict[int | None, list[int]]
    ) -> list[dict[str, Any]]:
        roots = children.get(None, [])
        current = active_root_id if active_root_id in nodes else (roots[-1] if roots else None)
        path: list[dict[str, Any]] = []
        visited: set[int] = set()
        while current is not None and current in nodes and current not in visited:
            visited.add(current)
            node = nodes[current]
            path.append(node)
            next_id = node["active_child_id"]
            if next_id is None or next_id not in nodes:
                siblings = children.get(current, [])
                next_id = siblings[-1] if siblings else None
            current = next_id
        return path

    @staticmethod
    def _decode_file_names(raw: Any) -> list[str] | None:
        if not raw:
            return None
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(parsed, list):
            return None
        names = [str(value) for value in parsed if isinstance(value, str)]
        return names or None

    def _serialize_path_node(
        self,
        node: dict[str, Any],
        children: dict[int | None, list[int]],
        *,
        include_attachment_contents: bool = False,
    ) -> dict[str, Any]:
        sibling_ids = children.get(node["parent_id"], [])
        try:
            version_index = sibling_ids.index(node["id"]) + 1
        except ValueError:
            version_index = 1
        entry: dict[str, Any] = {
            "id": node["id"],
            "message": node["message"],
            "sender": node["sender"],
            "timestamp": serialize_datetime_iso(node["timestamp"]),
            "version_index": version_index,
            "version_count": len(sibling_ids) or 1,
            "sibling_ids": list(sibling_ids),
        }
        names = self._decode_file_names(node.get("attached_file_names"))
        if names:
            entry["attached_file_names"] = names
        parts = decode_message_parts(node.get("message_parts"))
        if parts:
            entry["message_parts"] = parts
        if include_attachment_contents:
            attached = decode_attached_files_from_storage(node.get("attached_file_contents"))
            if attached:
                entry["attached_file_contents"] = [{"name": item.name, "content": item.content} for item in attached]
        return entry
