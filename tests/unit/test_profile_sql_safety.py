import unittest
from unittest.mock import AsyncMock, patch

from blueprints.chat.profile import _update_user_profile


class ProfilePersistenceBoundaryTestCase(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
