"""チャットルームの会話要約を、非同期の ChatRepository 経由で読み書きする。

Durable chat room summary state backed by the async Chat repository.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .chat_summary import build_room_summary_text
from .db import session_scope
from .repositories.chat_repository import ChatRepository

__all__ = [
    "get_room_summary",
    "rebuild_room_summary",
]


async def _read(operation, session: AsyncSession | None):
    """読み取り用に ChatRepository を用意して操作を実行する。session が無ければ自前のセッションを開く。

    Run an operation against a ChatRepository for reading; opens its own session when none is given.
    """
    if session is not None:
        return await operation(ChatRepository(session))
    async with session_scope() as scoped:
        return await operation(ChatRepository(scoped))


async def _write(operation, session: AsyncSession | None):
    """書き込み用に操作を実行する。session が無ければ自前のセッションでトランザクションを開く。
    渡されたセッションのトランザクションは呼び出し元が管理する。

    Run an operation for writing; opens its own transaction when no session is given, otherwise the caller owns the
    transaction.
    """
    if session is not None:
        return await operation(ChatRepository(session))
    async with session_scope() as scoped, scoped.begin():
        return await operation(ChatRepository(scoped))


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
    """アーカイブ済みの履歴から要約を作り直して保存する。要約文を返す。

    Rebuild the summary from the archived history, store it and return the summary text.
    """
    # 要約の生成はブロッキングな LLM クライアントを呼ぶことがあるため、別スレッドで実行する。DB 向けの run_blocking は使わず、
    # DB の処理とは切り離しておく。
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
