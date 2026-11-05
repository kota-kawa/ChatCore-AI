"""起動時の初期データ(標準タスク、サンプル投稿者、標準の共有プロンプト)を投入する永続化ヘルパー。

services/default_tasks.py と services/default_shared_prompts.py から呼ばれる。いずれも不足分だけを挿入し、再実行しても重複しない。

ORM/Core persistence helpers for startup seed data.
Called from services/default_tasks.py and services/default_shared_prompts.py; each inserts only what is missing,
so reruns do not duplicate rows.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import Prompt, Task, User, UserAuthProvider

# 日本語: 複数ワーカーが同時に起動しても重複投入しないための advisory lock ID(タスク用 / 共有プロンプト用)。
# English: Advisory-lock IDs (tasks / shared prompts) that keep several workers starting at once from seeding duplicates.
DEFAULT_TASK_SEED_ADVISORY_LOCK_ID = 743_241_901
DEFAULT_SHARED_PROMPT_SEED_ADVISORY_LOCK_ID = 743_241_902


async def seed_default_tasks(
    session: AsyncSession,
    rows: Iterable[tuple[Any, ...]],
) -> int:
    # advisory lock付きの1トランザクションで、未登録のシステムタスクを追加する。
    """Insert missing shared system tasks under one advisory-locked transaction."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": DEFAULT_TASK_SEED_ADVISORY_LOCK_ID},
    )
    existing_rows = (
        await session.execute(
            select(Task.system_task_key, Task.name).where(Task.user_id.is_(None))
        )
    ).all()
    # 日本語: 既存判定は system_task_key と、小文字化・前後空白除去した名前の両方で行う(どちらかが一致すれば挿入しない)。
    # English: A task counts as existing if either its system_task_key or its trimmed, lower-cased name matches.
    existing_keys = {
        str(key) for key, _ in existing_rows if isinstance(key, str) and key
    }
    existing_names = {
        str(name).strip().lower() for _, name in existing_rows if isinstance(name, str)
    }

    inserted = 0
    for (
        system_task_key,
        system_task_revision,
        name,
        prompt_template,
        response_rules,
        output_skeleton,
        input_examples,
        output_examples,
        display_order,
    ) in rows:
        normalized_name = str(name).strip().lower()
        if (
            system_task_key and system_task_key in existing_keys
        ) or normalized_name in existing_names:
            continue

        statement = insert(Task).values(
            user_id=None,
            system_task_key=system_task_key,
            system_task_revision=system_task_revision,
            name=name,
            prompt_template=prompt_template,
            response_rules=response_rules,
            output_skeleton=output_skeleton,
            input_examples=input_examples,
            output_examples=output_examples,
            display_order=display_order,
        )
        # 日本語: ON CONFLICT DO NOTHING の rowcount で実際に挿入されたものだけ数える。
        # English: Only rows actually inserted (per rowcount under ON CONFLICT DO NOTHING) are counted.
        result = await session.execute(statement.on_conflict_do_nothing())
        if int(getattr(result, "rowcount", 0) or 0) > 0:
            if system_task_key:
                existing_keys.add(str(system_task_key))
            existing_names.add(normalized_name)
            inserted += 1
    return inserted


async def ensure_sample_prompt_owner(
    session: AsyncSession,
    *,
    email: str,
    username: str,
) -> int:
    """サンプル投稿の所有者ユーザーを返す(無ければ認証 ID ごと作成する)。

    Return the stable sample owner, creating its auth identity atomically.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": DEFAULT_SHARED_PROMPT_SEED_ADVISORY_LOCK_ID},
    )
    await session.execute(
        insert(User)
        .values(email=email, username=username, is_verified=True)
        .on_conflict_do_nothing(index_elements=[User.email])
    )
    owner_id = await session.scalar(select(User.id).where(User.email == email))
    if owner_id is None:
        raise RuntimeError("Failed to create sample prompt owner.")

    provider_statement = insert(UserAuthProvider).values(
        user_id=owner_id,
        provider="email",
        provider_user_id=email,
        provider_email=email,
    )
    await session.execute(
        provider_statement.on_conflict_do_update(
            index_elements=[UserAuthProvider.user_id, UserAuthProvider.provider],
            set_={
                "provider_user_id": provider_statement.excluded.provider_user_id,
                "provider_email": provider_statement.excluded.provider_email,
                "updated_at": func.current_timestamp(),
            },
        )
    )
    return int(owner_id)


async def seed_default_shared_prompts(
    session: AsyncSession,
    *,
    owner_user_id: int,
    owner_name: str,
    prompts: Iterable[dict[str, Any]],
) -> int:
    """不足している言語別の公開システムプロンプトを、1 トランザクションで挿入する。

    (system_prompt_key, content_locale) の組が既にあるものはスキップする。

    Insert missing localized public system prompts in one transaction.
    """
    existing_rows = (
        await session.execute(
            select(Prompt.system_prompt_key, Prompt.content_locale).where(
                Prompt.user_id == owner_user_id,
                Prompt.deleted_at.is_(None),
                Prompt.system_prompt_key.is_not(None),
                Prompt.content_locale.is_not(None),
            )
        )
    ).all()
    existing_variants = {(str(key), str(locale)) for key, locale in existing_rows}

    inserted = 0
    for prompt in prompts:
        variant = (str(prompt["system_prompt_key"]), str(prompt["content_locale"]))
        if variant in existing_variants:
            continue
        await session.execute(
            insert(Prompt).values(
                user_id=owner_user_id,
                is_public=True,
                system_prompt_key=prompt["system_prompt_key"],
                content_locale=prompt["content_locale"],
                title=prompt["title"],
                category=prompt["category"],
                content=prompt["content"],
                author=owner_name,
                input_examples=prompt["input_examples"],
                output_examples=prompt["output_examples"],
                created_at=func.now(),
            )
        )
        existing_variants.add(variant)
        inserted += 1
    return inserted
