"""Async SQLAlchemy persistence for users and account-owned data."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

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


_USER_BY_ID_FIELDS = (
    "id",
    "email",
    "is_verified",
    "created_at",
    "username",
    "bio",
    "avatar_url",
    "llm_profile_context",
    "preferred_locale",
)


def _serialize_user(
    user: User,
    provider: UserAuthProvider | None = None,
    *,
    google_provider_lookup: bool = False,
) -> dict[str, Any]:
    """Convert a SQLAlchemy user entity to the legacy service payload shape."""

    payload = {
        column.key: getattr(user, column.key)
        for column in User.__table__.columns
    }
    if provider is not None:
        payload.update(
            auth_provider=provider.provider,
            provider_user_id=provider.provider_user_id,
            provider_email=provider.provider_email,
        )
    elif google_provider_lookup:
        # get_user_by_email historically exposes the optional Google provider
        # join.  Do not leak the email provider's legacy identity into the
        # Google-conflict check when no Google row exists.
        payload.update(
            auth_provider=None,
            provider_user_id=None,
            provider_email=None,
        )
    return payload


class UserRepository:
    """Persistence boundary for users, providers, and account deletion."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: int) -> dict[str, Any] | None:
        user = await self.session.scalar(
            select(User).where(User.id == int(user_id))
        )
        if user is None:
            return None
        payload = _serialize_user(user)
        return {field: payload[field] for field in _USER_BY_ID_FIELDS}

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        statement = (
            select(User, UserAuthProvider)
            .outerjoin(
                UserAuthProvider,
                (UserAuthProvider.user_id == User.id)
                & (UserAuthProvider.provider == "google"),
            )
            .where(User.email == email)
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        user, google_provider = row
        return _serialize_user(
            user,
            google_provider,
            google_provider_lookup=True,
        )

    async def get_by_google_id(self, google_user_id: str) -> dict[str, Any] | None:
        statement = (
            select(User, UserAuthProvider)
            .join(UserAuthProvider, UserAuthProvider.user_id == User.id)
            .where(
                UserAuthProvider.provider == "google",
                UserAuthProvider.provider_user_id == google_user_id,
            )
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        user, provider = row
        return _serialize_user(user, provider)

    async def _upsert_provider(
        self,
        *,
        user_id: int,
        provider: str,
        provider_user_id: str | None,
        provider_email: str | None,
    ) -> None:
        statement = (
            pg_insert(UserAuthProvider)
            .values(
                user_id=user_id,
                provider=provider,
                provider_user_id=provider_user_id,
                provider_email=provider_email,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "provider"],
                set_={
                    "provider_user_id": provider_user_id,
                    "provider_email": provider_email,
                    "updated_at": func.current_timestamp(),
                },
            )
        )
        await self.session.execute(statement)

    async def _sync_legacy_provider_columns(
        self,
        *,
        user_id: int,
        provider: str,
        provider_user_id: str | None,
        provider_email: str | None,
    ) -> None:
        # The current schema intentionally retains these columns for legacy
        # readers.  Keep them consistent with the normalized provider table.
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                auth_provider=provider,
                provider_user_id=provider_user_id,
                provider_email=provider_email,
            )
        )

    async def create(
        self,
        *,
        email: str,
        username: str,
        avatar_url: str,
        auth_provider: str,
        provider_user_id: str | None,
        provider_email: str | None,
        is_verified: bool,
        preferred_locale: str | None,
    ) -> int:
        user = User(
            email=email,
            username=username,
            avatar_url=avatar_url,
            is_verified=is_verified,
            auth_provider=auth_provider,
            provider_user_id=provider_user_id,
            provider_email=provider_email,
            preferred_locale=preferred_locale,
        )
        self.session.add(user)
        await self.session.flush()
        if user.id is None:  # pragma: no cover - PostgreSQL always returns SERIAL id
            raise RuntimeError("User insert did not return an ID.")

        await self._upsert_provider(
            user_id=user.id,
            provider=auth_provider,
            provider_user_id=provider_user_id,
            provider_email=provider_email,
        )
        return int(user.id)

    async def link_google_account(
        self,
        *,
        user_id: int,
        google_user_id: str,
        provider_email: str | None,
    ) -> None:
        await self._upsert_provider(
            user_id=user_id,
            provider="google",
            provider_user_id=google_user_id,
            provider_email=provider_email,
        )
        await self._sync_legacy_provider_columns(
            user_id=user_id,
            provider="google",
            provider_user_id=google_user_id,
            provider_email=provider_email,
        )

    async def update_profile_from_google_if_unset(
        self,
        *,
        user_id: int,
        username: str | None,
        avatar_url: str | None,
        default_username: str,
        default_avatar_url: str,
    ) -> None:
        user = await self.session.scalar(
            select(User).where(User.id == int(user_id))
        )
        if user is None:
            return

        next_username = user.username or default_username
        next_avatar_url = user.avatar_url or default_avatar_url
        if username and next_username.strip() in {"", default_username}:
            next_username = username
        if avatar_url and next_avatar_url.strip() in {"", default_avatar_url}:
            next_avatar_url = avatar_url

        await self.session.execute(
            update(User)
            .where(User.id == int(user_id))
            .values(username=next_username, avatar_url=next_avatar_url)
        )

    async def set_verified(self, user_id: int) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == int(user_id))
            .values(is_verified=True)
        )

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
