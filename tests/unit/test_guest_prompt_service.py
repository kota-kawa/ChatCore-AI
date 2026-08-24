import unittest
from unittest.mock import AsyncMock

from services.guest_prompt_service import (
    GuestPromptLimitExceeded,
    claim_guest_prompts_for_user,
    create_guest_shared_prompt,
    get_or_create_guest_prompt_token,
)
from services.request_models import SharedPromptCreateRequest


class _Repository:
    def __init__(self, *, prompt_id=88, retry_after=None, claimed=None):
        self.prompt_id = prompt_id
        self.retry_after = retry_after
        self.claimed = claimed or []
        self.create_calls = []
        self.claim_calls = []

    async def create_guest_prompt(self, session, **kwargs):
        self.create_calls.append((session, kwargs))
        return self.prompt_id, self.retry_after

    async def claim_guest_prompts(self, session, **kwargs):
        self.claim_calls.append((session, kwargs))
        return self.claimed


class GuestPromptServiceTestCase(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _payload():
        return SharedPromptCreateRequest.model_validate(
            {
                "title": "Guest text prompt",
                "description": "A short guest post description.",
                "content": "Write a concise introduction.",
                "content_format": "prompt",
                "media_type": "text",
            }
        )

    async def test_session_token_is_random_and_reused(self):
        session = {}
        token = get_or_create_guest_prompt_token(session)
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(get_or_create_guest_prompt_token(session), token)

    async def test_creation_leaves_caller_owned_transaction_open(self):
        repository = _Repository()
        session = AsyncMock()
        token = "guest-token-which-is-long-enough-to-be-valid"
        ip_address = "203.0.113.10"

        prompt_id = await create_guest_shared_prompt(
            token,
            ip_address,
            self._payload(),
            repository=repository,
            session=session,
        )

        self.assertEqual(prompt_id, 88)
        session.commit.assert_not_awaited()
        session.rollback.assert_not_awaited()
        kwargs = repository.create_calls[0][1]
        self.assertEqual(len(kwargs["cookie_hash"]), 64)
        self.assertEqual(len(kwargs["ip_hash"]), 64)
        self.assertNotIn(token, kwargs.values())
        self.assertNotIn(ip_address, kwargs.values())

    async def test_recent_submission_leaves_rollback_to_caller(self):
        repository = _Repository(retry_after=321)
        session = AsyncMock()
        with self.assertRaises(GuestPromptLimitExceeded) as raised:
            await create_guest_shared_prompt(
                "guest-token-which-is-long-enough-to-be-valid",
                "203.0.113.10",
                self._payload(),
                repository=repository,
                session=session,
            )
        self.assertEqual(raised.exception.retry_after, 321)
        session.rollback.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_claim_uses_cookie_hash_without_committing_caller_session(self):
        repository = _Repository(claimed=[88, 91])
        session = AsyncMock()
        prompt_ids = await claim_guest_prompts_for_user(
            7,
            "guest-token-which-is-long-enough-to-be-valid",
            repository=repository,
            session=session,
        )
        self.assertEqual(prompt_ids, [88, 91])
        session.commit.assert_not_awaited()
        session.rollback.assert_not_awaited()
        kwargs = repository.claim_calls[0][1]
        self.assertEqual(kwargs["user_id"], 7)
        self.assertEqual(len(kwargs["cookie_hash"]), 64)


if __name__ == "__main__":
    unittest.main()
