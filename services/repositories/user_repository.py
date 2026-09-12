"""Async SQLAlchemy persistence for account-owned user data.

This repository owns the ``users`` row itself: the profile fields, the
sign-in email and the preferred locale, plus account deletion and the
bundled task seed.  Authentication provider metadata stays in
:mod:`services.repositories.auth_identity_repository`, and the Skill
preference column stays with the Skill repository that owns that feature.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.avatar_storage import normalize_avatar_url
from services.models import (
    ChatRoom,
    MemoEntry,
    MemoryFact,
    Prompt,
    PromptLike,
    Task,
    User,
    UserAuthProvider,
    UserPasskey,
)


class UserRepository:
    """Repository for the ``users`` row, its profile fields and account cleanup.

    The repository never commits.  Services own the transaction and pass an
    isolated ``AsyncSession`` for one unit of work.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Profile and preferences ------------------------------------------------

    async def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        user = await self.session.get(User, user_id)
        return self._serialize_user(user) if user is not None else None

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        user = await self.session.scalar(select(User).where(User.email == email).limit(1))
        return self._serialize_user(user) if user is not None else None

    async def list_active_avatar_urls(self) -> list[str]:
        """Read every avatar URL still referenced by a user row.

        アバターの孤児ファイル掃除は、プロンプト添付と同じく DB を正として
        照合する。保存済みの値は正規化せずそのまま返し、旧形式のURLも
        参照済みとして扱えるようにする。
        English: The avatar reconciler treats the database as the source of
        truth. Stored values are returned verbatim so legacy URLs still count
        as referenced.
        """
        values = await self.session.scalars(select(User.avatar_url).where(User.avatar_url.is_not(None)))
        return [str(value) for value in values if value]

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

    # Account lifecycle ------------------------------------------------------

    async def delete_account(self, user_id: int) -> bool:
        user = await self.session.scalar(
            select(User)
            .where(User.id == int(user_id))
            .with_for_update()
        )
        if user is None:
            return False

        # These are the explicit deletes from the legacy account workflow.
        # Other user-owned rows use ON DELETE CASCADE from users and are
        # removed by the final ORM delete in the same transaction.
        for model in (
            PromptLike,
            MemoEntry,
            MemoryFact,
            UserAuthProvider,
            UserPasskey,
            ChatRoom,
            Task,
            Prompt,
        ):
            await self.session.execute(
                delete(model).where(model.user_id == int(user_id))
            )

        await self.session.execute(
            delete(User).where(User.id == int(user_id))
        )
        return True

    async def copy_default_tasks(self, user_id: int) -> None:
        """Copy the bundled catalog while retaining the advisory-lock semantics."""

        from services.default_tasks import default_task_rows

        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:user_id)"),
            {"user_id": int(user_id)},
        )
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
        ) in default_task_rows(include_key=True):
            existing_id = await self.session.scalar(
                select(Task.id)
                .where(
                    Task.user_id == int(user_id),
                    or_(
                        Task.system_task_key == system_task_key,
                        func.lower(func.btrim(Task.name))
                        == func.lower(func.btrim(name)),
                    ),
                )
                .limit(1)
            )
            if existing_id is not None:
                continue

            statement = (
                pg_insert(Task)
                .values(
                    user_id=int(user_id),
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
                .on_conflict_do_nothing()
            )
            await self.session.execute(statement)

    # Internal helpers -------------------------------------------------------

    @staticmethod
    def _serialize_user(user: User) -> dict[str, Any]:
        # Authentication-provider metadata lives in ``user_auth_providers``.
        # The legacy provider columns were removed from ``users`` when the ORM
        # was aligned with the normalized schema, so keep this payload limited
        # to fields owned by the User entity.
        return {
            "id": user.id,
            "email": user.email,
            "is_verified": user.is_verified,
            "created_at": user.created_at,
            "username": user.username,
            "bio": user.bio,
            # 旧 `/static/uploads/...` を現行の配信URLへ読み替えて返す。
            # Rewrite the legacy `/static/uploads/...` value to the served URL.
            "avatar_url": normalize_avatar_url(user.avatar_url),
            "llm_profile_context": user.llm_profile_context,
            "generative_ui_skill_enabled": user.generative_ui_skill_enabled,
            "preferred_locale": user.preferred_locale,
        }
