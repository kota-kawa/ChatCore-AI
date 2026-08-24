"""Durable chat memory and summary state backed by the async Chat repository."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .chat_summary import build_room_summary_text
from .db import session_scope
from .memory_extraction import extract_memory_facts
from .repositories.chat_repository import ChatRepository

MAX_MEMORY_FACTS_FOR_CONTEXT = 8

__all__ = [
    "extract_memory_facts",
    "get_room_summary",
    "list_room_memory_facts",
    "rebuild_room_summary",
    "remember_facts_from_message",
]


async def _read(operation, session: AsyncSession | None):
    if session is not None:
        return await operation(ChatRepository(session))
    async with session_scope() as scoped:
        return await operation(ChatRepository(scoped))


async def _write(operation, session: AsyncSession | None):
    if session is not None:
        return await operation(ChatRepository(session))
    async with session_scope() as scoped:
        async with scoped.begin():
            return await operation(ChatRepository(scoped))


async def list_room_memory_facts(
    chat_room_id: str,
    *,
    limit: int = MAX_MEMORY_FACTS_FOR_CONTEXT,
    session: AsyncSession | None = None,
) -> list[str]:
    return await _read(lambda repo: repo.list_room_memory_facts(chat_room_id, limit=limit), session)


async def remember_facts_from_message(
    chat_room_id: str,
    user_id: int,
    message: str,
    *,
    source_message_id: int | None = None,
    session: AsyncSession | None = None,
) -> list[str]:
    # LLM extraction is synchronous and non-DB work.  Run it off the event
    # loop, then perform only the persistence step through AsyncSession.
    facts = await asyncio.to_thread(extract_memory_facts, message)
    if not facts:
        return []
    await _write(
        lambda repo: repo.remember_facts(
            chat_room_id,
            user_id,
            facts,
            source_message_id=source_message_id,
        ),
        session,
    )
    return facts


async def get_room_summary(
    chat_room_id: str,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    return await _read(lambda repo: repo.get_room_summary(chat_room_id), session)


async def rebuild_room_summary(
    chat_room_id: str,
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    session: AsyncSession | None = None,
) -> str:
    # Summary generation may call a blocking LLM client; it is deliberately
    # isolated from the DB migration and never uses DB-oriented run_blocking.
    summary_text, archived_count = await asyncio.to_thread(
        build_room_summary_text,
        messages,
        model=model,
    )
    return await _write(
        lambda repo: repo.rebuild_room_summary(chat_room_id, summary_text, archived_count),
        session,
    )
