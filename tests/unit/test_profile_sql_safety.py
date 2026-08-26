import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from blueprints.chat.profile import _update_user_profile, user_profile
from services.models import User
from services.repositories.chat_repository import ChatRepository
from services.repositories.user_repository import _serialize_user
from tests.helpers.request_helpers import build_request


class ProfilePersistenceBoundaryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_profile_get_returns_the_async_repository_payload(self):
        request = build_request(
            method="GET",
            path="/api/user/profile",
            session={"user_id": 7},
        )
        profile = {
            "id": 7,
            "email": "alice@example.com",
            "username": "alice",
            "bio": "hello",
            "avatar_url": "/static/user-icon.png",
            "llm_profile_context": None,
        }

        with patch(
            "blueprints.chat.profile.get_user_by_id",
            new=AsyncMock(return_value=profile),
        ) as get_user:
            response = await user_profile(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body), {
            "username": "alice",
            "email": "alice@example.com",
            "bio": "hello",
            "avatar_url": "/static/user-icon.png",
            "llm_profile_context": None,
        })
        get_user.assert_awaited_once_with(7)

    async def test_profile_update_excludes_email_and_forwards_profile_fields(self):
        with patch(
            "blueprints.chat.profile.update_user_profile",
            new=AsyncMock(),
        ) as update:
            await _update_user_profile(
                user_id=10,
                username="alice",
                email="alice@example.com",
                bio="hello",
                avatar_url="/static/uploads/alice.png",
                llm_profile_context="日本語で簡潔に答えてください",
            )

        update.assert_awaited_once_with(
            10,
            username="alice",
            bio="hello",
            avatar_url="/static/uploads/alice.png",
            llm_profile_context="日本語で簡潔に答えてください",
        )
        self.assertNotIn("email", update.call_args.kwargs)

    async def test_profile_repository_error_is_propagated_for_route_handling(self):
        with patch(
            "blueprints.chat.profile.update_user_profile",
            new=AsyncMock(side_effect=RuntimeError("db error")),
        ):
            with self.assertRaises(RuntimeError):
                await _update_user_profile(12, "charlie", "charlie@example.com", "bio", None, "丁寧に答える")


class UserSerializerSchemaBoundaryTestCase(unittest.IsolatedAsyncioTestCase):
    def _user(self):
        return User(
            id=7,
            email="alice@example.com",
            username="alice",
            bio="hello",
            avatar_url="/static/user-icon.png",
            is_verified=True,
            llm_profile_context=None,
            preferred_locale="ja",
        )

    def test_chat_serializer_only_reads_columns_present_on_user_model(self):
        payload = ChatRepository._serialize_user(self._user())

        self.assertEqual(payload["username"], "alice")
        self.assertEqual(payload["preferred_locale"], "ja")
        self.assertNotIn("auth_provider", payload)
        self.assertNotIn("provider_user_id", payload)
        self.assertNotIn("provider_email", payload)

    async def test_chat_repository_get_user_by_id_uses_current_user_schema(self):
        session = Mock()
        session.get = AsyncMock(return_value=self._user())

        payload = await ChatRepository(session).get_user_by_id(7)

        session.get.assert_awaited_once_with(User, 7)
        self.assertEqual(payload["email"], "alice@example.com")
        self.assertNotIn("provider_user_id", payload)

    def test_email_lookup_serializer_does_not_read_removed_provider_columns(self):
        payload = _serialize_user(self._user(), google_provider_lookup=True)

        self.assertIsNone(payload["auth_provider"])
        self.assertIsNone(payload["provider_user_id"])
        self.assertIsNone(payload["provider_email"])


if __name__ == "__main__":
    unittest.main()
