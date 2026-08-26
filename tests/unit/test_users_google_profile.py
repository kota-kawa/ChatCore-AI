import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

from services.users import update_user_profile_from_google_if_unset


@asynccontextmanager
async def fake_session_scope(session):
    yield session


class GoogleProfileSyncTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_updates_default_username_and_avatar_from_google(self):
        session = Mock()
        session.commit = AsyncMock()
        repository = Mock()
        repository.update_profile_from_google_if_unset = AsyncMock()

        with patch("services.users.AuthIdentityRepository", return_value=repository), patch(
            "services.users.session_scope", return_value=fake_session_scope(session)
        ):
            await update_user_profile_from_google_if_unset(
                7,
                name="Alice Example",
                picture="https://example.com/alice.png",
            )

        repository.update_profile_from_google_if_unset.assert_awaited_once_with(
            user_id=7,
            username="Alice Example",
            avatar_url="https://example.com/alice.png",
            default_username="ユーザー",
            default_avatar_url="/static/user-icon.png",
        )
        session.commit.assert_awaited_once()

    async def test_preserves_existing_custom_profile_values_in_repository(self):
        session = Mock()
        session.commit = AsyncMock()
        repository = Mock()
        repository.update_profile_from_google_if_unset = AsyncMock()

        with patch("services.users.AuthIdentityRepository", return_value=repository), patch(
            "services.users.session_scope", return_value=fake_session_scope(session)
        ):
            await update_user_profile_from_google_if_unset(
                8,
                name="Google Name",
                picture="https://example.com/google.png",
            )

        repository.update_profile_from_google_if_unset.assert_awaited_once()
        session.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
