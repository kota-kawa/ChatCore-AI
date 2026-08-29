"""Async SQLAlchemy persistence boundary for chat-owned data."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, delete, func, literal, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError, ForbiddenOperationError, ResourceNotFoundError
from services.attached_files import decode_attached_files_from_storage, encode_attached_files_for_storage
from services.datetime_serialization import serialize_datetime_iso
from services.default_tasks import localize_system_task, resolve_system_task_key
from services.error_messages import (
    ERROR_CHAT_ROOM_NOT_FOUND,
    ERROR_SHARED_LINK_NOT_FOUND,
    ERROR_SKILL_LIMIT_REACHED,
    ERROR_SKILL_NAME_CONFLICT,
    ERROR_SKILL_NOT_FOUND,
    ERROR_SHARED_SKILL_CONTENT_MISSING,
    ERROR_TASK_NAME_CONFLICT,
    ERROR_TASK_NOT_FOUND,
    ERROR_TASK_ORDER_INVALID,
)
from services.generative_ui import decode_message_parts, encode_message_parts
from services.i18n import get_current_locale
from services.models import (
    ChatHistory,
    ChatRoom,
    ChatRoomSummary,
    MemoryFact,
    Project,
    SharedChatRoom,
    Task,
    User,
    UserSkill,
)
from services.user_skills import (
    MAX_USER_SKILL_NAME_LENGTH,
    MAX_USER_SKILLS,
    normalize_user_skill_instructions,
    normalize_user_skill_name,
)

UNIQUE_VIOLATION_PGCODE = "23505"
DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05
SHARED_TOKEN_MAX_COLLISION_RETRIES = 5
TASK_WRITE_LOCK_NAMESPACE = 1_413_567_307
USER_SKILL_WRITE_LOCK_NAMESPACE = 1_413_567_308


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


def _sqlstate(exc: BaseException) -> str | None:
    current: BaseException | None = exc
    for _ in range(4):
        if current is None:
            return None
        value = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if value:
            return str(value)
        original = getattr(current, "orig", None)
        current = original if isinstance(original, BaseException) else None
    return None


def _is_unique_violation(exc: BaseException) -> bool:
    return _sqlstate(exc) == UNIQUE_VIOLATION_PGCODE


class ChatRepository:
    """Repository for chat rooms, history, chat state, projects, tasks and profile rows.

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
        if parent_id is None:
            await self.session.execute(
                update(ChatRoom).where(ChatRoom.id == chat_room_id).values(active_root_id=record.id)
            )
        else:
            await self.session.execute(
                update(ChatHistory)
                .where(ChatHistory.id == parent_id, ChatHistory.chat_room_id == chat_room_id)
                .values(active_child_id=record.id)
            )
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
            .order_by(ChatRoom.created_at.desc(), ChatRoom.id.desc())
        )
        if cursor is not None:
            stmt = stmt.where(
                or_(
                    ChatRoom.created_at < cursor[0],
                    and_(ChatRoom.created_at == cursor[0], ChatRoom.id < cursor[1]),
                )
            )
        if limit is not None:
            stmt = stmt.limit(limit)
        return [self._serialize_room(room) for room in (await self.session.execute(stmt)).scalars().all()]

    async def delete_room_for_user(self, room_id: str, user_id: int) -> dict[str, str]:
        room = await self._owned_room(room_id, user_id, "他ユーザーのチャットルームは削除できません", lock=True)
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
        room = await self._owned_room(room_id, user_id, "", lock=True, forbidden_returns_false=True)
        if room is None:
            return False
        nodes, active_root_id = await self._load_room_tree(room_id)
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
        nodes, active_root_id = await self._load_room_tree(chat_room_id)
        children = self._children_by_parent(nodes)
        path = self._walk_active_path(nodes, active_root_id, children)
        return [
            self._serialize_path_node(node, children, include_attachment_contents=include_attachment_contents)
            for node in path
        ]

    async def get_active_leaf_id(self, chat_room_id: str) -> int | None:
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
        nodes, active_root_id = await self._load_room_tree(chat_room_id)
        path = self._walk_active_path(nodes, active_root_id, self._children_by_parent(nodes))
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

    async def get_active_path_web_search_contexts(self, chat_room_id: str) -> list[dict[str, Any]]:
        nodes, active_root_id = await self._load_room_tree(chat_room_id)
        path = self._walk_active_path(nodes, active_root_id, self._children_by_parent(nodes))
        contexts: list[dict[str, Any]] = []
        for node in path:
            decoded = _decode_web_search_context(node.get("web_search_context"))
            if decoded:
                contexts.extend(decoded)
        return contexts

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

    async def create_or_get_shared_chat_token(self, room_id: str, user_id: int) -> str:
        await self._owned_room(room_id, user_id, "他ユーザーのチャットルームは共有できません")
        for _ in range(SHARED_TOKEN_MAX_COLLISION_RETRIES):
            token = self._token_generator(18)
            statement = (
                pg_insert(SharedChatRoom)
                .values(chat_room_id=room_id, share_token=token)
                .on_conflict_do_update(
                    index_elements=[SharedChatRoom.chat_room_id],
                    set_={"chat_room_id": room_id},
                )
                .returning(SharedChatRoom.share_token)
            )
            try:
                # A collision must roll back only this insert attempt.  The
                # caller may have other writes in the surrounding service
                # transaction, so rolling back the whole AsyncSession here
                # would silently discard unrelated work.
                async with self.session.begin_nested():
                    row = (await self.session.execute(statement)).first()
                return str(row[0]) if row else token
            except IntegrityError as exc:
                if not _is_unique_violation(exc):
                    raise
                await asyncio.sleep(DB_RETRY_BACKOFF_SECONDS)
                await self._owned_room(room_id, user_id, "他ユーザーのチャットルームは共有できません")
        raise RuntimeError("Failed to create shared chat token after collision retries.")

    async def get_shared_chat_room_payload(self, token: str) -> dict[str, Any]:
        row = (
            await self.session.execute(
                select(ChatRoom.id, ChatRoom.title, ChatRoom.created_at)
                .join(SharedChatRoom, SharedChatRoom.chat_room_id == ChatRoom.id)
                .where(SharedChatRoom.share_token == token)
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            raise ResourceNotFoundError(ERROR_SHARED_LINK_NOT_FOUND)
        room_id, title, created_at = row
        nodes, active_root_id = await self._load_room_tree(room_id)
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
        nodes, active_root_id = await self._load_room_tree(chat_room_id)
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

    # User skills ------------------------------------------------------------

    async def list_user_skills(self, user_id: int) -> list[dict[str, Any]]:
        skills = (
            await self.session.execute(
                select(UserSkill)
                .where(UserSkill.user_id == user_id)
                .order_by(UserSkill.created_at, UserSkill.id)
            )
        ).scalars().all()
        return [self._serialize_user_skill(skill) for skill in skills]

    async def list_enabled_user_skills(self, user_id: int) -> list[dict[str, Any]]:
        skills = (
            await self.session.execute(
                select(UserSkill)
                .where(UserSkill.user_id == user_id, UserSkill.is_enabled.is_(True))
                .order_by(UserSkill.created_at, UserSkill.id)
            )
        ).scalars().all()
        return [self._serialize_user_skill(skill) for skill in skills]

    async def create_user_skill(
        self,
        user_id: int,
        name: str,
        instructions: str,
    ) -> dict[str, Any]:
        normalized_name = normalize_user_skill_name(name)
        normalized_instructions = normalize_user_skill_instructions(instructions)
        await self._lock_user_skills(user_id)
        skill_count = await self.session.scalar(
            select(func.count(UserSkill.id)).where(UserSkill.user_id == user_id)
        )
        if int(skill_count or 0) >= MAX_USER_SKILLS:
            raise ApiServiceError(ERROR_SKILL_LIMIT_REACHED, 409, code="skill_limit_reached")

        duplicate = await self.session.scalar(
            select(UserSkill.id)
            .where(
                UserSkill.user_id == user_id,
                func.lower(func.btrim(UserSkill.name)) == func.lower(func.btrim(normalized_name)),
            )
            .limit(1)
        )
        if duplicate is not None:
            raise ApiServiceError(ERROR_SKILL_NAME_CONFLICT, 409, code="skill_name_conflict")

        skill = UserSkill(
            user_id=user_id,
            name=normalized_name,
            instructions=normalized_instructions,
            is_enabled=True,
        )
        self.session.add(skill)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                raise ApiServiceError(ERROR_SKILL_NAME_CONFLICT, 409, code="skill_name_conflict") from exc
            raise
        return self._serialize_user_skill(skill)

    async def import_user_skill(
        self,
        user_id: int,
        source_prompt_id: int,
        name: str,
        instructions: str,
    ) -> tuple[dict[str, Any], bool]:
        """Create or return a Skill imported from a shared prompt.

        The same per-user advisory lock as the regular Skill editor is used so
        the limit and normalized-name allocation remain atomic across both
        entry points.  ``source_prompt_id`` is deliberately nullable at the
        schema level so manually-created Skills and deleted shared prompts are
        still supported, but imported rows are identified by this value while
        their source remains public.
        """
        normalized_name = normalize_user_skill_name(name) or "共有Skill"
        normalized_instructions = normalize_user_skill_instructions(instructions)
        if not normalized_instructions:
            raise ApiServiceError(ERROR_SHARED_SKILL_CONTENT_MISSING, 400, code="skill_content_missing")

        await self._lock_user_skills(user_id)
        existing = (
            await self.session.execute(
                select(UserSkill)
                .where(
                    UserSkill.user_id == int(user_id),
                    UserSkill.source_prompt_id == int(source_prompt_id),
                )
                .order_by(UserSkill.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return self._serialize_user_skill(existing), False

        skill_count = await self.session.scalar(
            select(func.count(UserSkill.id)).where(UserSkill.user_id == int(user_id))
        )
        if int(skill_count or 0) >= MAX_USER_SKILLS:
            raise ApiServiceError(ERROR_SKILL_LIMIT_REACHED, 409, code="skill_limit_reached")

        skill_name = await self._available_imported_skill_name(
            user_id=int(user_id),
            name=normalized_name,
        )
        skill = UserSkill(
            user_id=int(user_id),
            source_prompt_id=int(source_prompt_id),
            name=skill_name,
            instructions=normalized_instructions,
            is_enabled=True,
        )
        self.session.add(skill)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                raise ApiServiceError(ERROR_SKILL_NAME_CONFLICT, 409, code="skill_name_conflict") from exc
            raise
        return self._serialize_user_skill(skill), True

    async def delete_user_skill_by_source_prompt(self, user_id: int, source_prompt_id: int) -> bool:
        """Delete the Skill imported from a shared prompt, if it exists."""
        await self._lock_user_skills(user_id)
        result = await self.session.execute(
            delete(UserSkill).where(
                UserSkill.user_id == int(user_id),
                UserSkill.source_prompt_id == int(source_prompt_id),
            )
        )
        await self.session.flush()
        return bool(result.rowcount or 0)

    async def set_user_skill_enabled(
        self,
        user_id: int,
        skill_id: int,
        is_enabled: bool,
    ) -> dict[str, Any]:
        skill = await self._owned_user_skill(skill_id, user_id, lock=True)
        skill.is_enabled = is_enabled
        skill.updated_at = datetime.utcnow()
        await self.session.flush()
        return self._serialize_user_skill(skill)

    async def delete_user_skill(self, user_id: int, skill_id: int) -> None:
        skill = await self._owned_user_skill(skill_id, user_id, lock=True)
        await self.session.delete(skill)
        await self.session.flush()

    # Tasks ------------------------------------------------------------------

    async def fetch_tasks(self, user_id: int | None, locale: str) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(Task)
                .where(Task.user_id == user_id, Task.deleted_at.is_(None))
                .order_by(func.coalesce(Task.display_order, 99999), Task.id)
            )
        ).scalars().all()
        return [self._localize_task(task, locale, is_default=False) for task in rows]

    async def get_task_prompt_data(
        self, task: str, user_id: int | None, task_id: int | None = None
    ) -> dict[str, Any] | None:
        columns = (
            Task.id.label("task_id"),
            Task.system_task_key,
            Task.system_task_revision,
            Task.is_system_task_customized,
            Task.name,
            Task.prompt_template,
            Task.response_rules,
            Task.output_skeleton,
            Task.input_examples,
            Task.output_examples,
        )
        if task_id is not None:
            stmt = select(*columns).where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
        else:
            key = resolve_system_task_key(task)
            lookup_column = Task.system_task_key if key is not None else Task.name
            stmt = select(*columns).where(lookup_column == (key or task), Task.deleted_at.is_(None))
            if user_id:
                stmt = stmt.where(or_(Task.user_id == user_id, Task.user_id.is_(None))).order_by(
                    case((Task.user_id == user_id, 0), else_=1), Task.id
                )
            else:
                stmt = stmt.where(Task.user_id.is_(None)).order_by(Task.id)
            stmt = stmt.limit(1)
        row = (await self.session.execute(stmt)).mappings().first()
        return localize_system_task(dict(row), get_current_locale()) if row is not None else None

    async def update_tasks_order(self, user_id: int, new_order: list[int]) -> None:
        await self._lock_user_tasks(user_id)
        rows = (
            await self.session.execute(
                select(Task.id).where(Task.user_id == user_id, Task.deleted_at.is_(None)).with_for_update()
            )
        ).all()
        active_ids = {int(task_id) for (task_id,) in rows}
        if len(new_order) != len(active_ids) or set(new_order) != active_ids:
            raise ApiServiceError(ERROR_TASK_ORDER_INVALID, 400, code="invalid_task_order")
        for index, task_id in enumerate(new_order):
            result = await self.session.execute(
                update(Task)
                .where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
                .values(display_order=index, updated_at=func.current_timestamp())
            )
            if result.rowcount != 1:
                raise ApiServiceError(ERROR_TASK_ORDER_INVALID, 400, code="invalid_task_order")

    async def delete_task(self, user_id: int, task_id: int) -> None:
        await self._lock_user_tasks(user_id)
        result = await self.session.execute(
            update(Task)
            .where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
            .values(deleted_at=func.current_timestamp(), updated_at=func.current_timestamp())
        )
        if result.rowcount != 1:
            raise ResourceNotFoundError(ERROR_TASK_NOT_FOUND, code="task_not_found")

    async def edit_task(
        self,
        user_id: int,
        task_id: int,
        new_task: str,
        prompt_template: str | None,
        response_rules: str | None,
        output_skeleton: str | None,
        input_examples: str | None,
        output_examples: str | None,
    ) -> bool:
        await self._lock_user_tasks(user_id)
        task = (
            await self.session.execute(
                select(Task)
                .where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if task is None:
            raise ResourceNotFoundError(ERROR_TASK_NOT_FOUND, code="task_not_found")
        duplicate = await self.session.scalar(
            select(Task.id)
            .where(
                Task.user_id == user_id,
                Task.id != task_id,
                Task.deleted_at.is_(None),
                func.lower(func.btrim(Task.name)) == func.lower(func.btrim(new_task)),
            )
            .limit(1)
        )
        if duplicate is not None:
            raise ApiServiceError(ERROR_TASK_NAME_CONFLICT, 409, code="task_name_conflict")
        task.name = new_task
        for field, value in (
            ("prompt_template", prompt_template),
            ("response_rules", response_rules),
            ("output_skeleton", output_skeleton),
            ("input_examples", input_examples),
            ("output_examples", output_examples),
        ):
            if value is not None:
                setattr(task, field, value)
        if task.system_task_key is not None:
            task.is_system_task_customized = True
        await self.session.flush()
        return True

    async def add_task(
        self,
        user_id: int,
        title: str,
        prompt_content: str,
        response_rules: str,
        output_skeleton: str,
        input_examples: str,
        output_examples: str,
    ) -> None:
        await self._lock_user_tasks(user_id)
        duplicate = await self.session.scalar(
            select(Task.id)
            .where(
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
                func.lower(func.btrim(Task.name)) == func.lower(func.btrim(title)),
            )
            .limit(1)
        )
        if duplicate is not None:
            raise ApiServiceError(ERROR_TASK_NAME_CONFLICT, 409, code="task_name_conflict")
        next_order = await self.session.scalar(
            select(func.coalesce(func.max(Task.display_order), -1) + 1).where(
                Task.user_id == user_id, Task.deleted_at.is_(None)
            )
        )
        self.session.add(
            Task(
                user_id=user_id,
                name=title,
                prompt_template=prompt_content,
                response_rules=response_rules,
                output_skeleton=output_skeleton,
                input_examples=input_examples,
                output_examples=output_examples,
                display_order=int(next_order or 0),
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                raise ApiServiceError(ERROR_TASK_NAME_CONFLICT, 409, code="task_name_conflict") from exc
            raise

    # Projects ---------------------------------------------------------------

    async def create_project(self, user_id: int, name: str, instructions: str | None = None) -> dict[str, Any]:
        project = Project(
            user_id=user_id,
            name=self._normalize_project_name(name),
            instructions=self._normalize_project_instructions(instructions),
        )
        self.session.add(project)
        await self.session.flush()
        return self._serialize_project(project)

    async def list_projects(self, user_id: int) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(Project, func.count(ChatRoom.id).label("chat_count"))
                .outerjoin(ChatRoom, ChatRoom.project_id == Project.id)
                .where(Project.user_id == user_id)
                .group_by(Project.id)
                .order_by(Project.created_at.desc(), Project.id.desc())
            )
        ).all()
        projects: list[dict[str, Any]] = []
        for project, count in rows:
            payload = self._serialize_project(project)
            payload["chatCount"] = int(count or 0)
            projects.append(payload)
        return projects

    async def get_project(self, project_id: int, user_id: int) -> dict[str, Any]:
        project = await self._owned_project(project_id, user_id)
        rooms = (
            await self.session.execute(
                select(ChatRoom)
                .where(ChatRoom.project_id == project_id)
                .order_by(ChatRoom.created_at.desc(), ChatRoom.id.desc())
            )
        ).scalars().all()
        payload = self._serialize_project(project)
        payload["rooms"] = [self._serialize_room(room, project_room=True) for room in rooms]
        return payload

    async def list_project_rooms(self, project_id: int, user_id: int) -> list[dict[str, Any]]:
        await self._owned_project(project_id, user_id)
        rooms = (
            await self.session.execute(
                select(ChatRoom)
                .where(ChatRoom.project_id == project_id)
                .order_by(ChatRoom.created_at.desc(), ChatRoom.id.desc())
            )
        ).scalars().all()
        return [self._serialize_room(room, project_room=True) for room in rooms]

    async def update_project(
        self,
        project_id: int,
        user_id: int,
        *,
        name: str | None = None,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        project = await self._owned_project(project_id, user_id, lock=True)
        if name is not None:
            project.name = self._normalize_project_name(name)
        if instructions is not None:
            project.instructions = self._normalize_project_instructions(instructions)
        project.updated_at = datetime.utcnow()
        await self.session.flush()
        return self._serialize_project(project)

    async def delete_project(self, project_id: int, user_id: int) -> None:
        await self.session.delete(await self._owned_project(project_id, user_id, lock=True))

    async def assign_room_to_project(self, room_id: str, user_id: int, project_id: int | None) -> None:
        await self._owned_room(room_id, user_id, "他ユーザーのチャットルームは操作できません", lock=True)
        if project_id is not None:
            await self._owned_project(project_id, user_id)
        await self.session.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(project_id=project_id))

    async def get_project_context(self, room_id: str) -> dict[str, Any] | None:
        row = (
            await self.session.execute(
                select(Project.id, Project.name, Project.instructions)
                .join(ChatRoom, ChatRoom.project_id == Project.id)
                .where(ChatRoom.id == room_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return {"project_id": row[0], "name": str(row[1] or ""), "instructions": str(row[2] or "").strip()}

    # Users and preferences --------------------------------------------------

    async def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        user = await self.session.get(User, user_id)
        return self._serialize_user(user) if user is not None else None

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        user = await self.session.scalar(select(User).where(User.email == email).limit(1))
        return self._serialize_user(user) if user is not None else None

    async def update_user_profile(
        self,
        user_id: int,
        *,
        username: str,
        bio: str,
        avatar_url: str | None,
        llm_profile_context: str,
    ) -> bool:
        values: dict[str, Any] = {
            "username": username,
            "bio": bio,
            "llm_profile_context": llm_profile_context,
        }
        if avatar_url is not None:
            values["avatar_url"] = avatar_url
        result = await self.session.execute(update(User).where(User.id == user_id).values(**values))
        return bool(result.rowcount)

    async def commit_email_change(self, user_id: int, new_email: str) -> bool:
        current = await self.session.scalar(
            select(User).where(func.lower(User.email) == func.lower(new_email)).with_for_update()
        )
        if current is not None and current.id != user_id:
            return False
        result = await self.session.execute(update(User).where(User.id == user_id).values(email=new_email))
        return bool(result.rowcount)

    async def get_user_preferred_locale(self, user_id: int) -> str | None:
        return await self.session.scalar(select(User.preferred_locale).where(User.id == user_id))

    async def update_user_preferred_locale(self, user_id: int, locale: str) -> bool:
        result = await self.session.execute(update(User).where(User.id == user_id).values(preferred_locale=locale))
        return bool(result.rowcount)

    # Internal helpers -------------------------------------------------------

    async def _load_room_tree(self, chat_room_id: str) -> tuple[dict[int, dict[str, Any]], int | None]:
        rows = (
            await self.session.execute(
                select(ChatHistory).where(ChatHistory.chat_room_id == chat_room_id).order_by(ChatHistory.id)
            )
        ).scalars().all()
        nodes: dict[int, dict[str, Any]] = {}
        for row in rows:
            nodes[int(row.id)] = {
                "id": row.id,
                "message": row.message,
                "sender": row.sender,
                "parent_id": row.parent_id,
                "active_child_id": row.active_child_id,
                "timestamp": row.timestamp,
                "attached_file_names": row.attached_file_names,
                "message_parts": row.message_parts,
                "attached_file_contents": row.attached_file_contents,
                "web_search_context": row.web_search_context,
            }
        active_root_id = await self.session.scalar(select(ChatRoom.active_root_id).where(ChatRoom.id == chat_room_id))
        return nodes, active_root_id

    async def _owned_room(
        self,
        room_id: str,
        user_id: int,
        forbidden_message: str,
        *,
        lock: bool = False,
        forbidden_returns_false: bool = False,
    ) -> ChatRoom | None:
        stmt = select(ChatRoom).where(ChatRoom.id == room_id)
        if lock:
            stmt = stmt.with_for_update()
        room = (await self.session.execute(stmt)).scalar_one_or_none()
        if room is None:
            if forbidden_returns_false:
                return None
            raise ResourceNotFoundError(ERROR_CHAT_ROOM_NOT_FOUND)
        if room.user_id != user_id:
            if forbidden_returns_false:
                return None
            raise ForbiddenOperationError(forbidden_message)
        return room

    async def _owned_project(self, project_id: int, user_id: int, *, lock: bool = False) -> Project:
        stmt = select(Project).where(Project.id == project_id)
        if lock:
            stmt = stmt.with_for_update()
        project = (await self.session.execute(stmt)).scalar_one_or_none()
        if project is None:
            raise ResourceNotFoundError("プロジェクトが見つかりません")
        if project.user_id != user_id:
            raise ForbiddenOperationError("他ユーザーのプロジェクトは操作できません")
        return project

    async def _owned_user_skill(self, skill_id: int, user_id: int, *, lock: bool = False) -> UserSkill:
        stmt = select(UserSkill).where(UserSkill.id == skill_id, UserSkill.user_id == user_id)
        if lock:
            stmt = stmt.with_for_update()
        skill = (await self.session.execute(stmt)).scalar_one_or_none()
        if skill is None:
            raise ResourceNotFoundError(ERROR_SKILL_NOT_FOUND, code="skill_not_found")
        return skill

    async def _lock_user_tasks(self, user_id: int) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :user_id)").bindparams(
                namespace=TASK_WRITE_LOCK_NAMESPACE, user_id=user_id
            )
        )

    async def _lock_user_skills(self, user_id: int) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :user_id)").bindparams(
                namespace=USER_SKILL_WRITE_LOCK_NAMESPACE, user_id=user_id
            )
        )

    async def _available_imported_skill_name(self, *, user_id: int, name: str) -> str:
        """Allocate a deterministic Skill name without colliding with manual Skills."""
        base_name = normalize_user_skill_name(name) or "共有Skill"
        candidate = base_name
        suffix_number = 1
        while True:
            existing = await self.session.scalar(
                select(UserSkill.id)
                .where(
                    UserSkill.user_id == int(user_id),
                    func.lower(func.btrim(UserSkill.name)) == func.lower(func.btrim(candidate)),
                )
                .limit(1)
            )
            if existing is None:
                return candidate
            suffix_number += 1
            suffix = f" ({suffix_number})"
            candidate = f"{base_name[: MAX_USER_SKILL_NAME_LENGTH - len(suffix)]}{suffix}"

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

    @staticmethod
    def _serialize_room(room: ChatRoom, *, project_room: bool = False) -> dict[str, Any]:
        payload = {
            "id": room.id,
            "title": room.title or "新規チャット",
            "mode": room.mode or "normal",
            "created_at": serialize_datetime_iso(room.created_at),
        }
        if project_room:
            payload["createdAt"] = payload.pop("created_at")
        return payload

    @staticmethod
    def _normalize_project_name(name: Any) -> str:
        return (str(name or "").strip() or "新規プロジェクト")[:255]

    @staticmethod
    def _normalize_project_instructions(instructions: Any) -> str | None:
        return None if instructions is None else str(instructions)[:20_000]

    @staticmethod
    def _serialize_project(project: Project) -> dict[str, Any]:
        return {
            "id": project.id,
            "name": str(project.name or "新規プロジェクト"),
            "instructions": str(project.instructions or ""),
            "createdAt": serialize_datetime_iso(project.created_at),
            "updatedAt": serialize_datetime_iso(project.updated_at),
        }

    @staticmethod
    def _serialize_user_skill(skill: UserSkill) -> dict[str, Any]:
        return {
            "id": skill.id,
            "name": str(skill.name or ""),
            "instructions": str(skill.instructions or ""),
            "is_enabled": bool(skill.is_enabled),
            "created_at": serialize_datetime_iso(skill.created_at),
            "updated_at": serialize_datetime_iso(skill.updated_at),
        }

    @staticmethod
    def _localize_task(task: Task, locale: str, *, is_default: bool) -> dict[str, Any]:
        return localize_system_task(
            {
                "task_id": task.id,
                "system_task_key": task.system_task_key,
                "system_task_revision": task.system_task_revision,
                "is_system_task_customized": task.is_system_task_customized,
                "name": task.name,
                "prompt_template": task.prompt_template,
                "response_rules": task.response_rules,
                "output_skeleton": task.output_skeleton,
                "input_examples": task.input_examples,
                "output_examples": task.output_examples,
                "is_default": is_default,
            },
            locale,
        )

    @staticmethod
    def _serialize_user(user: User) -> dict[str, Any]:
        # Authentication-provider metadata lives in ``user_auth_providers``.
        # The legacy provider columns were removed from ``users`` when the ORM
        # was aligned with the normalized schema, so keep this chat-facing
        # payload limited to fields owned by the User entity.
        return {
            "id": user.id,
            "email": user.email,
            "is_verified": user.is_verified,
            "created_at": user.created_at,
            "username": user.username,
            "bio": user.bio,
            "avatar_url": user.avatar_url,
            "llm_profile_context": user.llm_profile_context,
            "preferred_locale": user.preferred_locale,
        }
