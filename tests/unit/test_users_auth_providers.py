import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

from services.users import (
    DEFAULT_AVATAR_URL,
    EMAIL_AUTH_PROVIDER,
    GOOGLE_AUTH_PROVIDER,
    create_user,
    delete_user_account,
    get_user_by_email,
    get_user_by_google_id,
    get_user_by_id,
    link_google_account,
)


@asynccontextmanager
async def fake_session_scope(session):
    yield session


def repository_harness():
    session = Mock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    repository = Mock()
    repository.get_by_id = AsyncMock()
    repository.get_by_email = AsyncMock()
    repository.get_by_google_id = AsyncMock()
    repository.create = AsyncMock()
    repository.link_google_account = AsyncMock()
    repository.delete_account = AsyncMock()
    return session, repository


class UserAuthProvidersTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_get_user_by_id_uses_async_repository(self):
        session, repository = repository_harness()
        expected = {"id": 7, "email": "user@example.com", "preferred_locale": "en"}
        repository.get_by_id.return_value = expected

        with patch("services.users.UserRepository", return_value=repository), patch(
            "services.users.session_scope",
            side_effect=lambda: fake_session_scope(session),
        ):
            result = await get_user_by_id(7)

        self.assertEqual(result, expected)
        repository.get_by_id.assert_awaited_once_with(7)
        session.commit.assert_not_awaited()

    async def test_create_user_commits_user_and_provider_workflow(self):
        session, repository = repository_harness()
        repository.create.return_value = 321

        with patch("services.users.UserRepository", return_value=repository), patch(
            "services.users.session_scope", return_value=fake_session_scope(session)
        ):
            user_id = await create_user("user@example.com")

        self.assertEqual(user_id, 321)
        repository.create.assert_awaited_once_with(
            email="user@example.com",
            username="ユーザー",
            avatar_url=DEFAULT_AVATAR_URL,
            auth_provider=EMAIL_AUTH_PROVIDER,
            provider_user_id="user@example.com",
            provider_email="user@example.com",
            is_verified=False,
            preferred_locale=None,
        )
        session.commit.assert_awaited_once()

    async def test_create_user_normalizes_google_avatar_and_provider_metadata(self):
        session, repository = repository_harness()
        repository.create.return_value = 322
        long_avatar_url = "https://example.com/" + ("a" * 260)

        with patch("services.users.UserRepository", return_value=repository), patch(
            "services.users.session_scope", return_value=fake_session_scope(session)
        ):
            user_id = await create_user(
                "user@example.com",
                avatar_url=long_avatar_url,
                auth_provider=GOOGLE_AUTH_PROVIDER,
                provider_user_id="google-user-123",
                provider_email="user@example.com",
                is_verified=True,
            )

        self.assertEqual(user_id, 322)
        call = repository.create.await_args.kwargs
        self.assertEqual(call["avatar_url"], DEFAULT_AVATAR_URL)
        self.assertEqual(call["provider_user_id"], "google-user-123")
        self.assertTrue(call["is_verified"])

    async def test_link_google_account_commits_upsert(self):
        session, repository = repository_harness()

        with patch("services.users.UserRepository", return_value=repository), patch(
            "services.users.session_scope", return_value=fake_session_scope(session)
        ):
            await link_google_account(7, "google-user-123", "user@example.com")

        repository.link_google_account.assert_awaited_once_with(
            user_id=7,
            google_user_id="google-user-123",
            provider_email="user@example.com",
        )
        session.commit.assert_awaited_once()

    async def test_provider_lookups_delegate_to_the_matching_repository_method(self):
        session, repository = repository_harness()
        email_user = {"id": 10, "email": "user@example.com", "provider_user_id": "google-user-999"}
        google_user = {"id": 9, "email": "user@example.com", "provider_user_id": "google-user-123"}
        repository.get_by_email.return_value = email_user
        repository.get_by_google_id.return_value = google_user

        with patch("services.users.UserRepository", return_value=repository), patch(
            "services.users.session_scope",
            side_effect=lambda: fake_session_scope(session),
        ):
            self.assertEqual(await get_user_by_email("user@example.com"), email_user)
            self.assertEqual(await get_user_by_google_id("google-user-123"), google_user)

        repository.get_by_email.assert_awaited_once_with("user@example.com")
        repository.get_by_google_id.assert_awaited_once_with("google-user-123")

    async def test_delete_account_commits_existing_user(self):
        session, repository = repository_harness()
        repository.delete_account.return_value = True

        with patch("services.users.UserRepository", return_value=repository), patch(
            "services.users.session_scope", return_value=fake_session_scope(session)
        ):
            self.assertTrue(await delete_user_account(7))

        repository.delete_account.assert_awaited_once_with(7)
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    async def test_delete_account_rolls_back_when_user_is_missing(self):
        session, repository = repository_harness()
        repository.delete_account.return_value = False

        with patch("services.users.UserRepository", return_value=repository), patch(
            "services.users.session_scope", return_value=fake_session_scope(session)
        ):
            self.assertFalse(await delete_user_account(7))

        session.commit.assert_not_awaited()
        session.rollback.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
