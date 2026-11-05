"""チャット関連のユースケースを非同期関数として公開するサービス層。
各ユースケースは対象の行を持つリポジトリ（チャットルーム・履歴は ChatRepository、プロジェクト、タスク、Skill、
アカウントのプロフィールはそれぞれ専用のリポジトリ）に処理を任せる。
このモジュールはトランザクションの境界を持ち、Chat のブループリントから呼ばれる公開関数名を安定させる。

Async Chat use-case services.

Each use case runs against the repository that owns its rows: chat rooms and
history in :class:`ChatRepository`, projects in :class:`ProjectRepository`,
tasks in :class:`TaskRepository`, Skills in :class:`UserSkillRepository` and
account-owned profile rows in :class:`UserRepository`.  This module owns the
transaction boundary and keeps the public function names stable for the Chat
blueprints.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from .api_errors import ForbiddenOperationError
from .db import is_retryable_db_error, session_scope
from .error_messages import ERROR_DEFAULT_SKILL_IMMUTABLE
from .repositories.chat_repository import (
    DB_RETRY_BACKOFF_SECONDS,
    DB_WRITE_MAX_ATTEMPTS,
    ChatRepository,
)
from .repositories.project_repository import ProjectRepository
from .repositories.task_repository import TaskRepository
from .repositories.user_repository import UserRepository
from .repositories.user_skill_repository import UserSkillRepository
from .share_common import serialize_token_share_lifecycle
from .tool_approval_parts import TOOL_APPROVAL_PART_TYPE, redact_tool_approval_for_share, tool_approval_part
from .user_skills import (
    SYSTEM_SKILL_KEYS,
    build_system_skill,
    system_skill_key_for_id,
)

T = TypeVar("T")


@asynccontextmanager
async def _transaction(session: AsyncSession | None, *, write: bool):
    """独立したセッションを渡し、commit / rollback をサービス層の端で行う。
    呼び出し元がセッションを渡した場合はそれをそのまま使う。

    Yield an isolated session and keep commit/rollback at the service edge.
    """

    if session is None:
        async with session_scope() as scoped:
            if write:
                async with scoped.begin():
                    yield scoped
            else:
                yield scoped
        return

    # 呼び出し元が渡したセッションは、外側のサービスやユースケースのもの。
    # 複数のリポジトリ呼び出しを 1 つの原子的な操作にまとめるため、そのトランザクションは開いたままにする。
    # A caller-provided session belongs to the surrounding service/use case.
    # Keeping its transaction open is required when several repository calls
    # are composed into one atomic operation.
    yield session


def _chat(session: AsyncSession) -> ChatRepository:
    return ChatRepository(session)


def _chat_with_token_generator(token_generator: Callable[[int], str]) -> Callable[[AsyncSession], ChatRepository]:
    """共有トークンの生成関数を差し替えられる ChatRepository のファクトリを作る（テストで固定トークンを使うため）。

    Build a chat repository factory that uses an injected share-token source.
    """

    return lambda session: ChatRepository(session, token_generator=token_generator)


async def _read(
    operation: Callable[[Any], Awaitable[T]],
    session: AsyncSession | None,
    *,
    repository: Callable[[AsyncSession], Any] = _chat,
) -> T:
    """読み取り用のトランザクションでリポジトリ操作を 1 回実行する。repository で ChatRepository 以外も選べる。

    Run one repository operation in a read transaction; repository selects a repository other than ChatRepository.
    """
    async with _transaction(session, write=False) as scoped:
        return await operation(repository(scoped))


async def _write(
    operation: Callable[[Any], Awaitable[T]],
    session: AsyncSession | None,
    *,
    repository: Callable[[AsyncSession], Any] = _chat,
) -> T:
    """書き込み用のトランザクションでリポジトリ操作を実行する。session が無いときは、
    再試行できる DB エラーを回数上限まで間隔を空けて再試行する。
    session を渡された場合は呼び出し元がトランザクションを持つので再試行しない。

    Run a repository operation in a write transaction. Without a session, retryable DB errors are retried with backoff
    up to the attempt limit; a caller-provided session owns its transaction, so there is no retry.
    """
    if session is not None:
        async with _transaction(session, write=True) as scoped:
            return await operation(repository(scoped))

    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        try:
            async with _transaction(None, write=True) as scoped:
                return await operation(repository(scoped))
        except Exception as exc:
            if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                await asyncio.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise
    raise RuntimeError("Database write retry attempts exhausted.")


async def save_message_to_db(
    chat_room_id: str,
    message: str,
    sender: str,
    attached_file_names: list[str] | None = None,
    parent_id: int | None = None,
    message_parts: list[dict[str, Any]] | None = None,
    attached_file_contents: list[Any] | None = None,
    web_search_context: list[dict[str, Any]] | None = None,
    attached_images: list[Any] | None = None,
    *,
    session: AsyncSession | None = None,
) -> int | None:
    return await _write(
        lambda repo: repo.save_message(
            chat_room_id,
            message,
            sender,
            attached_file_names,
            parent_id,
            message_parts,
            attached_file_contents,
            web_search_context,
            attached_images,
        ),
        session,
    )


async def store_user_message_and_load_turn_context(
    chat_room_id: str,
    message: str,
    sender: str = "user",
    attached_file_names: list[str] | None = None,
    message_parts: list[dict[str, Any]] | None = None,
    attached_file_contents: list[Any] | None = None,
    attached_images: list[Any] | None = None,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """ユーザー発話を 1 件追加し、そのターンに必要な文脈を返す。ルームの木を 1 回読むだけで済ませる。
    分岐の先端、LLM に渡す履歴、過去の Web 検索の根拠が同じスナップショットから得られるため、
    1 回の投稿で接続を 3 本使うことがなくなった（オーバーフロー無しのプール設定のため）。

    Append one chat turn and return the context it needs, using a single room-tree read.

    The branch tip, the LLM history and the prior web-search evidence all come
    from the same snapshot, so one chat post no longer takes three connections
    out of a pool configured without overflow.
    """

    return await _write(
        lambda repo: repo.store_user_message_and_load_turn_context(
            chat_room_id,
            message,
            sender,
            attached_file_names,
            message_parts,
            attached_file_contents,
            attached_images,
        ),
        session,
    )


async def get_active_path(
    chat_room_id: str,
    *,
    include_attachment_contents: bool = False,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    return await _read(
        lambda repo: repo.get_active_path(
            chat_room_id,
            include_attachment_contents=include_attachment_contents,
        ),
        session,
    )


async def get_active_leaf_id(chat_room_id: str, *, session: AsyncSession | None = None) -> int | None:
    return await _read(lambda repo: repo.get_active_leaf_id(chat_room_id), session)


async def switch_chat_branch(
    chat_room_id: str,
    target_id: int,
    *,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    return await _write(lambda repo: repo.switch_branch(chat_room_id, target_id), session)


async def create_chat_room_in_db(
    room_id: str,
    user_id: int,
    title: str,
    mode: str = "normal",
    *,
    session: AsyncSession | None = None,
) -> None:
    await _write(lambda repo: repo.create_room(room_id, user_id, title, mode), session)


async def delete_unanswered_user_messages(
    room_id: str,
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> bool:
    return await _write(lambda repo: repo.delete_unanswered_user_messages(room_id, user_id), session)


async def rename_chat_room_in_db(
    room_id: str,
    new_title: str,
    *,
    session: AsyncSession | None = None,
) -> None:
    await _write(lambda repo: repo.rename_room(room_id, new_title), session)


async def rename_chat_room_if_current_title_in(
    room_id: str,
    new_title: str,
    allowed_current_titles: list[str],
    *,
    session: AsyncSession | None = None,
) -> bool:
    return await _write(
        lambda repo: repo.rename_room_if_current_title_in(room_id, new_title, allowed_current_titles),
        session,
    )


async def get_chat_room_messages(
    chat_room_id: str,
    *,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    return await _read(lambda repo: repo.get_room_messages_for_llm(chat_room_id), session)


async def get_room_web_search_contexts(
    chat_room_id: str,
    *,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    return await _read(lambda repo: repo.get_active_path_web_search_contexts(chat_room_id), session)


async def validate_room_owner(
    room_id: str,
    user_id: int,
    forbidden_message: str,
    *,
    session: AsyncSession | None = None,
) -> str | None:
    return await _read(lambda repo: repo.validate_room_owner(room_id, user_id, forbidden_message), session)


def _resolve_share_expires_at(expires_in_days: int | None) -> datetime | None:
    """共有リンクの有効日数を、UTC の絶対時刻へ変換する。shared_chat_rooms.expires_at は timestamptz なのでタイムゾーン付き
    にする（メモの共有リンクは timestamp 列で、専用の関数を使う）。

    Turn a share lifetime in days into an absolute UTC instant.

    ``shared_chat_rooms.expires_at`` is ``timestamptz``, so the value must be
    timezone-aware (memo share links use a naive ``timestamp`` column and keep
    their own helper).
    """

    if expires_in_days is None:
        return None
    return datetime.now(UTC) + timedelta(days=max(int(expires_in_days), 1))


def _serialize_chat_share_state(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return serialize_token_share_lifecycle(None, None, None)
    return serialize_token_share_lifecycle(
        row.get("share_token"),
        row.get("expires_at"),
        row.get("revoked_at"),
        is_reused=bool(row.get("is_reused")),
    )


async def create_or_get_shared_chat_token(
    room_id: str,
    user_id: int,
    *,
    expires_in_days: int | None = None,
    force_refresh: bool = False,
    session: AsyncSession | None = None,
    token_generator: Callable[[int], str] = secrets.token_urlsafe,
) -> dict[str, Any]:
    """ルームの共有リンクを作る。すでにあれば再利用し、リンクの状態（有効期限・失効など）を返す。

    Create or reuse a room's share link and return its lifecycle state.
    """

    expires_at = _resolve_share_expires_at(expires_in_days)
    row = await _write(
        lambda repo: repo.create_or_get_shared_chat_token(
            room_id,
            user_id,
            expires_at=expires_at,
            force_refresh=force_refresh,
        ),
        session,
        repository=_chat_with_token_generator(token_generator),
    )
    return _serialize_chat_share_state(row)


async def revoke_shared_chat_token(
    room_id: str,
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    """ルームの共有リンクを失効させる。共有リンクが無かったルームでは None を返す。

    Revoke a room's share link, or return ``None`` when it never had one.
    """

    row = await _write(lambda repo: repo.revoke_shared_chat_token(room_id, user_id), session)
    if row is None:
        return None
    return _serialize_chat_share_state(row)


# 共有表示と fork では承認カードを読み取り専用の最小限にする。提案の中身（非公開のメモ本文や差分）・
# 結果・警告を見せず、他人のカードを操作させないため。
# Shared views and forks reduce approval cards to a readonly minimum, so viewers never see the
# proposal (private memo text or diffs), its result or warnings, and cannot act on the card.
def _redact_shared_messages(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        return payload
    for message in messages:
        parts = message.get("message_parts") if isinstance(message, dict) else None
        if not isinstance(parts, list):
            continue
        message["message_parts"] = [
            tool_approval_part(redact_tool_approval_for_share(part["approval"]))
            if part.get("type") == TOOL_APPROVAL_PART_TYPE and isinstance(part.get("approval"), dict)
            else part
            for part in parts
        ]
    return payload


async def get_shared_chat_room_payload(
    token: str,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    return _redact_shared_messages(await _read(lambda repo: repo.get_shared_chat_room_payload(token), session))


async def fork_shared_chat_into_db_room(
    token: str,
    room_id: str,
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """共有された会話を、呼び出し元のトランザクション内で新しいルームへ複製する。承認カードは共有表示と同じ最小限の形にし、
    複製するのは先頭 500 件まで。

    Copy a shared conversation in one transaction owned by the caller.
    """

    async def operation(repo: ChatRepository) -> dict[str, Any]:
        payload = _redact_shared_messages(await repo.get_shared_chat_room_payload(token))
        room = payload.get("room") if isinstance(payload, dict) else None
        title = str((room or {}).get("title") or "共有チャット").strip() or "共有チャット"
        messages = [
            message
            for message in (payload.get("messages") if isinstance(payload, dict) else [])
            if isinstance(message, dict)
        ][:500]
        await repo.create_room(room_id, user_id, title, "normal")
        copied = await repo.copy_messages_into_room(room_id, messages)
        return {"id": room_id, "title": title, "mode": "normal", "message_count": copied}

    return await _write(operation, session)


async def get_task_prompt_data(
    task: str,
    user_id: int | None,
    task_id: int | None = None,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    return await _read(
        lambda repo: repo.get_task_prompt_data(task, user_id, task_id),
        session,
        repository=TaskRepository,
    )


async def list_chat_rooms(
    user_id: int,
    *,
    limit: int | None = None,
    cursor: tuple[Any, str] | None = None,
    session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    return await _read(lambda repo: repo.list_user_rooms(user_id, limit=limit, cursor=cursor), session)


async def list_pinned_chat_rooms(user_id: int, *, session: AsyncSession | None = None) -> list[dict[str, Any]]:
    return await _read(lambda repo: repo.list_pinned_user_rooms(user_id), session)


async def set_chat_room_pinned(
    room_id: str,
    user_id: int,
    pinned: bool,
    *,
    session: AsyncSession | None = None,
) -> str | None:
    return await _write(lambda repo: repo.set_room_pinned(room_id, user_id, pinned), session)


async def delete_chat_room_for_user(
    room_id: str,
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> dict[str, str]:
    return await _write(lambda repo: repo.delete_room_for_user(room_id, user_id), session)


async def delete_chat_rooms_for_user(
    room_ids: list[str],
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    return await _write(lambda repo: repo.delete_rooms_for_user(room_ids, user_id), session)


async def fetch_chat_history_page(
    chat_room_id: str,
    limit: int,
    before_message_id: int | None = None,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    return await _read(lambda repo: repo.fetch_chat_history_page(chat_room_id, limit, before_message_id), session)


# プロジェクト操作はここから公開し、Chat のブループリントが旧来の同期のプロジェクトサービスへ直接触れないようにする。
# Project operations are exposed here so Chat blueprints do not reach into the
# legacy synchronous project service.
async def create_project(user_id: int, name: str, instructions: str | None = None, *, session: AsyncSession | None = None):
    return await _write(
        lambda repo: repo.create_project(user_id, name, instructions),
        session,
        repository=ProjectRepository,
    )


async def list_projects(user_id: int, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.list_projects(user_id), session, repository=ProjectRepository)


async def get_project(project_id: int, user_id: int, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.get_project(project_id, user_id), session, repository=ProjectRepository)


async def list_project_rooms(project_id: int, user_id: int, *, session: AsyncSession | None = None):
    return await _read(
        lambda repo: repo.list_project_rooms(project_id, user_id),
        session,
        repository=ProjectRepository,
    )


async def update_project(
    project_id: int,
    user_id: int,
    *,
    name: str | None = None,
    instructions: str | None = None,
    session: AsyncSession | None = None,
):
    return await _write(
        lambda repo: repo.update_project(project_id, user_id, name=name, instructions=instructions),
        session,
        repository=ProjectRepository,
    )


async def delete_project(project_id: int, user_id: int, *, session: AsyncSession | None = None) -> None:
    await _write(lambda repo: repo.delete_project(project_id, user_id), session, repository=ProjectRepository)


async def assign_room_to_project(
    room_id: str,
    user_id: int,
    project_id: int | None,
    *,
    session: AsyncSession | None = None,
) -> None:
    await _write(
        lambda repo: repo.assign_room_to_project(room_id, user_id, project_id),
        session,
        repository=ProjectRepository,
    )


async def get_project_context(room_id: str, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.get_project_context(room_id), session, repository=ProjectRepository)


async def fetch_tasks(user_id: int | None, locale: str, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.fetch_tasks(user_id, locale), session, repository=TaskRepository)


async def get_owned_task(user_id: int, task_id: int, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.get_owned_task(user_id, task_id), session, repository=TaskRepository)


async def list_user_skills(user_id: int, *, session: AsyncSession | None = None):
    """組み込み Skill（利用者ごとの ON/OFF 状態付き）と、利用者自身の Skill を続けて返す。

    Return the built-in Skills (with this user's on/off state) followed by the user's own Skills.
    """
    async def operation(repo: UserSkillRepository):
        states = await repo.get_system_skill_states(user_id)
        personal_skills = await repo.list_user_skills(user_id)
        return [
            *(build_system_skill(key, is_enabled=states[key]) for key in SYSTEM_SKILL_KEYS),
            *personal_skills,
        ]

    return await _read(operation, session, repository=UserSkillRepository)


async def list_enabled_user_skills(user_id: int, *, session: AsyncSession | None = None):
    return await _read(
        lambda repo: repo.list_enabled_user_skills(user_id),
        session,
        repository=UserSkillRepository,
    )


async def list_personal_user_skills(user_id: int, *, session: AsyncSession | None = None):
    """組み込み Skill を混ぜず、この利用者自身の Skill だけを全項目付きで返す。

    List only this user's own Skills, in full, without the built-in Skills mixed in.
    """
    return await _read(lambda repo: repo.list_user_skills(user_id), session, repository=UserSkillRepository)


async def get_user_skill(user_id: int, skill_id: int, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.get_user_skill(user_id, skill_id), session, repository=UserSkillRepository)


async def update_user_skill(
    user_id: int,
    skill_id: int,
    *,
    name: str | None,
    instructions: str | None,
    expected_updated_at: str | None,
    session: AsyncSession | None = None,
):
    return await _write(
        lambda repo: repo.update_user_skill(
            user_id,
            skill_id,
            name=name,
            instructions=instructions,
            expected_updated_at=expected_updated_at,
        ),
        session,
        repository=UserSkillRepository,
    )


async def create_user_skill(
    user_id: int,
    name: str,
    instructions: str,
    *,
    session: AsyncSession | None = None,
):
    return await _write(
        lambda repo: repo.create_user_skill(user_id, name, instructions),
        session,
        repository=UserSkillRepository,
    )


async def set_user_skill_enabled(
    user_id: int,
    skill_id: int,
    is_enabled: bool,
    *,
    session: AsyncSession | None = None,
):
    """Skill の ON/OFF を切り替える。組み込み Skill は利用者ごとの状態として保存し、個人 Skill は Skill 行を更新する。

    Toggle a Skill. Built-in Skills store a per-user state; personal Skills update the Skill row.
    """
    system_key = system_skill_key_for_id(skill_id)
    if system_key is not None:
        next_enabled = bool(is_enabled)
        stored_enabled = await _write(
            lambda repo: repo.set_system_skill_enabled(user_id, system_key, next_enabled),
            session,
            repository=UserSkillRepository,
        )
        return build_system_skill(system_key, is_enabled=stored_enabled)
    return await _write(
        lambda repo: repo.set_user_skill_enabled(user_id, skill_id, is_enabled),
        session,
        repository=UserSkillRepository,
    )


async def delete_user_skill(
    user_id: int,
    skill_id: int,
    *,
    session: AsyncSession | None = None,
) -> None:
    """個人 Skill を削除する。組み込み Skill は削除できないので拒否する。

    Delete a personal Skill; built-in Skills are refused because they cannot be removed.
    """
    if system_skill_key_for_id(skill_id) is not None:
        raise ForbiddenOperationError(
            ERROR_DEFAULT_SKILL_IMMUTABLE,
            code="default_skill_immutable",
        )
    await _write(
        lambda repo: repo.delete_user_skill(user_id, skill_id),
        session,
        repository=UserSkillRepository,
    )


async def update_tasks_order(user_id: int, new_order: list[int], *, session: AsyncSession | None = None) -> None:
    await _write(lambda repo: repo.update_tasks_order(user_id, new_order), session, repository=TaskRepository)


async def delete_task(user_id: int, task_id: int, *, session: AsyncSession | None = None) -> None:
    await _write(lambda repo: repo.delete_task(user_id, task_id), session, repository=TaskRepository)


async def edit_task(
    user_id: int,
    task_id: int,
    new_task: str,
    prompt_template: str | None,
    response_rules: str | None,
    output_skeleton: str | None,
    input_examples: str | None,
    output_examples: str | None,
    *,
    expected_updated_at: str | None = None,
    session: AsyncSession | None = None,
) -> bool:
    return await _write(
        lambda repo: repo.edit_task(
            user_id,
            task_id,
            new_task,
            prompt_template,
            response_rules,
            output_skeleton,
            input_examples,
            output_examples,
            expected_updated_at=expected_updated_at,
        ),
        session,
        repository=TaskRepository,
    )


async def add_task(
    user_id: int,
    title: str,
    prompt_content: str,
    response_rules: str,
    output_skeleton: str,
    input_examples: str,
    output_examples: str,
    *,
    session: AsyncSession | None = None,
) -> int:
    return await _write(
        lambda repo: repo.add_task(
            user_id,
            title,
            prompt_content,
            response_rules,
            output_skeleton,
            input_examples,
            output_examples,
        ),
        session,
        repository=TaskRepository,
    )


async def get_room_summary(chat_room_id: str, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.get_room_summary(chat_room_id), session)


async def update_user_profile(
    user_id: int,
    *,
    username: str,
    bio: str,
    avatar_url: str | None,
    llm_profile_context: str,
    session: AsyncSession | None = None,
) -> bool:
    return await _write(
        lambda repo: repo.update_user_profile(
            user_id,
            username=username,
            bio=bio,
            avatar_url=avatar_url,
            llm_profile_context=llm_profile_context,
        ),
        session,
        repository=UserRepository,
    )


async def get_chat_profile_settings(
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    return await _read(
        lambda repo: repo.get_chat_profile_settings(user_id),
        session,
        repository=UserRepository,
    )


async def update_chat_profile_settings_if_unchanged(
    user_id: int,
    *,
    expected_fingerprint: str | None,
    updates: dict[str, Any],
    session: AsyncSession | None = None,
) -> bool | None:
    """期待した指紋（expected_fingerprint）と現在の設定が一致するときだけ更新する。
    提案した時点から設定が変わっていないことを確かめる更新。更新できたら True、変わっていたら False、
    利用者の行が消えていたら None を返す。

    Update only when the current settings still match expected_fingerprint, so nothing changed since the proposal.
    Returns True when updated, False when the settings changed, None when the user row is gone.
    """
    return await _write(
        lambda repo: repo.update_chat_profile_settings_if_unchanged(
            user_id,
            expected_fingerprint=expected_fingerprint,
            updates=updates,
        ),
        session,
        repository=UserRepository,
    )


async def commit_email_change(user_id: int, new_email: str, *, session: AsyncSession | None = None) -> bool:
    return await _write(
        lambda repo: repo.commit_email_change(user_id, new_email),
        session,
        repository=UserRepository,
    )


async def get_user_by_id(user_id: int, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.get_user_by_id(user_id), session, repository=UserRepository)


async def get_user_by_email(email: str, *, session: AsyncSession | None = None):
    return await _read(lambda repo: repo.get_user_by_email(email), session, repository=UserRepository)


async def get_user_preferred_locale(user_id: int, *, session: AsyncSession | None = None):
    return await _read(
        lambda repo: repo.get_user_preferred_locale(user_id),
        session,
        repository=UserRepository,
    )


async def update_user_preferred_locale(user_id: int, locale: str, *, session: AsyncSession | None = None) -> bool:
    return await _write(
        lambda repo: repo.update_user_preferred_locale(user_id, locale),
        session,
        repository=UserRepository,
    )
