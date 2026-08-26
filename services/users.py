"""User use cases backed by the async SQLAlchemy repositories."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .db import session_scope
from .i18n import Locale, normalize_locale
from .repositories.auth_identity_repository import AuthIdentityRepository
from .repositories.user_repository import UserRepository


DEFAULT_USERNAME = "ユーザー"
DEFAULT_AVATAR_URL = "/static/user-icon.png"
LEGACY_AVATAR_URL_MAX_LENGTH = 255
EMAIL_AUTH_PROVIDER = "email"
GOOGLE_AUTH_PROVIDER = "google"
ACCOUNT_DELETE_CONFIRMATION_TEXT = "DELETE ACCOUNT"


def _normalize_provider_metadata(
    auth_provider: str,
    email: str,
    provider_user_id: str | None,
    provider_email: str | None,
) -> tuple[str | None, str | None]:
    normalized_provider_user_id = (provider_user_id or "").strip() or None
    normalized_provider_email = (provider_email or "").strip() or None
    if auth_provider == EMAIL_AUTH_PROVIDER:
        normalized_provider_user_id = normalized_provider_user_id or email
        normalized_provider_email = normalized_provider_email or email
    return normalized_provider_user_id, normalized_provider_email


def _normalize_avatar_url(avatar_url: str | None) -> str:
    normalized = (avatar_url or "").strip()
    if not normalized or len(normalized) > LEGACY_AVATAR_URL_MAX_LENGTH:
        return DEFAULT_AVATAR_URL
    return normalized


@asynccontextmanager
async def _managed_session(
    session: AsyncSession | None,
) -> AsyncIterator[AsyncSession]:
    if session is not None:
        yield session
        return
    async with session_scope() as owned_session:
        yield owned_session


async def _run(
    operation: Callable[[UserRepository], Awaitable[Any]],
    *,
    session: AsyncSession | None,
    commit: bool | Callable[[Any], bool] = False,
) -> Any:
    async with _managed_session(session) as db_session:
        result = await operation(UserRepository(db_session))
        if session is None:
            should_commit = commit(result) if callable(commit) else commit
            if should_commit:
                await db_session.commit()
            elif commit is not False:
                await db_session.rollback()
        return result


async def _run_auth(
    operation: Callable[[AuthIdentityRepository], Awaitable[Any]],
    *,
    session: AsyncSession | None,
    commit: bool = False,
) -> Any:
    """Run authentication persistence through its dedicated schema boundary."""

    async with _managed_session(session) as db_session:
        result = await operation(AuthIdentityRepository(db_session))
        if session is None and commit:
            await db_session.commit()
        return result


async def copy_default_tasks_for_user(
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> None:
    """Copy the bundled tasks under the same transaction advisory lock."""

    await _run(
        lambda repository: repository.copy_default_tasks(int(user_id)),
        session=session,
        commit=True,
    )


async def get_user_by_email(
    email: str,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    return await _run_auth(
        lambda repository: repository.get_by_email(email),
        session=session,
    )


async def get_user_by_google_id(
    google_user_id: str,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    return await _run_auth(
        lambda repository: repository.get_by_google_id(google_user_id),
        session=session,
    )


async def get_user_by_id(
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    return await _run_auth(
        lambda repository: repository.get_by_id(int(user_id)),
        session=session,
    )


async def create_user(
    email: str,
    username: str | None = None,
    avatar_url: str | None = None,
    *,
    auth_provider: str = EMAIL_AUTH_PROVIDER,
    provider_user_id: str | None = None,
    provider_email: str | None = None,
    is_verified: bool = False,
    preferred_locale: Locale | None = None,
    session: AsyncSession | None = None,
) -> int | None:
    normalized_username = (username or "").strip()[:255] or DEFAULT_USERNAME
    normalized_avatar_url = _normalize_avatar_url(avatar_url)
    normalized_preferred_locale = normalize_locale(preferred_locale)
    if preferred_locale is not None and normalized_preferred_locale is None:
        raise ValueError("Unsupported preferred locale")
    normalized_provider_user_id, normalized_provider_email = _normalize_provider_metadata(
        auth_provider,
        email,
        provider_user_id,
        provider_email,
    )
    return await _run_auth(
        lambda repository: repository.create(
            email=email,
            username=normalized_username,
            avatar_url=normalized_avatar_url,
            auth_provider=auth_provider,
            provider_user_id=normalized_provider_user_id,
            provider_email=normalized_provider_email,
            is_verified=bool(is_verified),
            preferred_locale=normalized_preferred_locale,
        ),
        session=session,
        commit=True,
    )


async def link_google_account(
    user_id: int,
    google_user_id: str,
    provider_email: str,
    *,
    session: AsyncSession | None = None,
) -> None:
    normalized_google_user_id = (google_user_id or "").strip()
    if not normalized_google_user_id:
        raise ValueError("google_user_id is required")
    normalized_provider_email = (provider_email or "").strip() or None
    await _run_auth(
        lambda repository: repository.link_google_account(
            user_id=int(user_id),
            google_user_id=normalized_google_user_id,
            provider_email=normalized_provider_email,
        ),
        session=session,
        commit=True,
    )


async def update_user_profile_from_google_if_unset(
    user_id: int,
    name: str | None = None,
    picture: str | None = None,
    *,
    session: AsyncSession | None = None,
) -> None:
    normalized_name = (name or "").strip() or None
    normalized_picture = (picture or "").strip() or None
    if normalized_picture:
        normalized_picture = _normalize_avatar_url(normalized_picture)
    await _run_auth(
        lambda repository: repository.update_profile_from_google_if_unset(
            user_id=int(user_id),
            username=normalized_name,
            avatar_url=normalized_picture,
            default_username=DEFAULT_USERNAME,
            default_avatar_url=DEFAULT_AVATAR_URL,
        ),
        session=session,
        commit=True,
    )


async def delete_user_account(
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> bool:
    return await _run(
        lambda repository: repository.delete_account(int(user_id)),
        session=session,
        commit=lambda result: bool(result),
    )


async def set_user_verified(
    user_id: int,
    *,
    session: AsyncSession | None = None,
) -> None:
    await _run_auth(
        lambda repository: repository.set_verified(int(user_id)),
        session=session,
        commit=True,
    )
