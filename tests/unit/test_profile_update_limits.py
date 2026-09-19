import json
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from blueprints.chat.profile import user_profile
from services.error_messages import ERROR_PROFILE_INPUT_TOO_LONG, ERROR_USERNAME_REQUIRED
from services.request_models import (
    MAX_PROFILE_BIO_LENGTH,
    MAX_PROFILE_LLM_CONTEXT_LENGTH,
    MAX_PROFILE_USERNAME_LENGTH,
)
from tests.helpers.request_helpers import build_request

CURRENT_PROFILE = {
    "id": 7,
    "email": "alice@example.com",
    "username": "alice",
    "bio": "hello",
    "avatar_url": "/api/user/avatars/alice.png",
    "llm_profile_context": None,
}


# 日本語: プロフィール更新のフォーム送信を模したリクエストを組み立てます。
# English: Build a request that mimics a profile-update form submission.
def _profile_post(fields: dict[str, str]):
    return build_request(
        method="POST",
        path="/api/user/profile",
        session={"user_id": 7},
        raw_body=urlencode(fields).encode("utf-8"),
        headers=[(b"content-type", b"application/x-www-form-urlencoded")],
    )


class ProfileUpdateInputLimitTestCase(unittest.IsolatedAsyncioTestCase):
    """
    プロフィール更新の各テキスト項目に長さ上限が適用されることを検証するテストクラス。
    Verify that the profile-update text fields are capped before anything is persisted.
    """

    async def _post(self, fields: dict[str, str]):
        with patch(
            "blueprints.chat.profile.get_user_by_id",
            new=AsyncMock(return_value=CURRENT_PROFILE),
        ), patch(
            "blueprints.chat.profile.update_user_profile",
            new=AsyncMock(),
        ) as update:
            response = await user_profile(_profile_post(fields))
        return response, update

    async def test_rejects_username_longer_than_the_cap(self):
        response, update = await self._post({"username": "a" * (MAX_PROFILE_USERNAME_LENGTH + 1)})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.body)["error"], ERROR_PROFILE_INPUT_TOO_LONG)
        update.assert_not_awaited()

    async def test_rejects_bio_longer_than_the_cap(self):
        response, update = await self._post(
            {"username": "alice", "bio": "b" * (MAX_PROFILE_BIO_LENGTH + 1)}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.body)["error"], ERROR_PROFILE_INPUT_TOO_LONG)
        update.assert_not_awaited()

    async def test_rejects_llm_profile_context_longer_than_the_cap(self):
        response, update = await self._post(
            {
                "username": "alice",
                "llm_profile_context": "c" * (MAX_PROFILE_LLM_CONTEXT_LENGTH + 1),
            }
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.body)["error"], ERROR_PROFILE_INPUT_TOO_LONG)
        update.assert_not_awaited()

    async def test_accepts_fields_at_the_cap_and_persists_them(self):
        bio = "b" * MAX_PROFILE_BIO_LENGTH
        llm_profile_context = "c" * MAX_PROFILE_LLM_CONTEXT_LENGTH
        response, update = await self._post(
            {
                "username": "alice",
                "email": "alice@example.com",
                "bio": bio,
                "llm_profile_context": llm_profile_context,
            }
        )

        self.assertEqual(response.status_code, 200)
        update.assert_awaited_once_with(
            7,
            username="alice",
            bio=bio,
            avatar_url=None,
            llm_profile_context=llm_profile_context,
        )

    async def test_still_requires_a_username(self):
        response, update = await self._post({"username": "   ", "bio": "hello"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.body)["error"], ERROR_USERNAME_REQUIRED)
        update.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
