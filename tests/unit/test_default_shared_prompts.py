import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import ANY, AsyncMock, patch

from services.default_shared_prompts import (
    DEFAULT_SHARED_PROMPTS,
    ensure_default_shared_prompts,
)


@asynccontextmanager
async def _session_scope():
    class _Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    class _Session:
        def begin(self):
            return _Transaction()

    yield _Session()


class DefaultSharedPromptsTestCase(unittest.TestCase):
    def test_samples_have_stable_keys_and_both_locales(self):
        grouped = {}
        for prompt in DEFAULT_SHARED_PROMPTS:
            grouped.setdefault(prompt["system_prompt_key"], set()).add(
                prompt["content_locale"]
            )

        self.assertTrue(grouped)
        self.assertTrue(all(locales == {"ja", "en"} for locales in grouped.values()))

    def test_inserts_samples_in_one_async_transaction(self):
        owner = AsyncMock(return_value=999)
        seed = AsyncMock(return_value=len(DEFAULT_SHARED_PROMPTS))
        with (
            patch("services.default_shared_prompts.session_scope", new=_session_scope),
            patch("services.default_shared_prompts.ensure_sample_prompt_owner", new=owner),
            patch("services.default_shared_prompts.seed_default_shared_prompts", new=seed),
        ):
            inserted = asyncio.run(ensure_default_shared_prompts())

        self.assertEqual(inserted, len(DEFAULT_SHARED_PROMPTS))
        owner.assert_awaited_once_with(
            ANY,
            email="sample-prompts@chat-core.local",
            username="運営サンプル",
        )
        seed.assert_awaited_once()
        self.assertEqual(seed.await_args.kwargs["owner_user_id"], 999)

    def test_returns_zero_when_repository_finds_no_missing_rows(self):
        owner = AsyncMock(return_value=999)
        seed = AsyncMock(return_value=0)
        with (
            patch("services.default_shared_prompts.session_scope", new=_session_scope),
            patch("services.default_shared_prompts.ensure_sample_prompt_owner", new=owner),
            patch("services.default_shared_prompts.seed_default_shared_prompts", new=seed),
        ):
            inserted = asyncio.run(ensure_default_shared_prompts())

        self.assertEqual(inserted, 0)
        seed.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
