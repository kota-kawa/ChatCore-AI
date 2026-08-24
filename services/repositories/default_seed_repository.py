"""ORM/Core persistence helpers for startup seed data."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import Prompt, Task, User, UserAuthProvider


DEFAULT_TASK_SEED_ADVISORY_LOCK_ID = 743_241_901
DEFAULT_SHARED_PROMPT_SEED_ADVISORY_LOCK_ID = 743_241_902


async def seed_default_tasks(
    session: AsyncSession,
    rows: Iterable[tuple[Any, ...]],
) -> int:
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
    """Return the stable sample owner, creating its auth identity atomically."""
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
    """Insert missing localized public system prompts in one transaction."""
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
