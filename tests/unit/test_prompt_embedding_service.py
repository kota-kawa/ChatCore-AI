import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects.postgresql import dialect

from services import prompt_embedding_service
from services.prompt_embedding_service import (
    build_prompt_embedding_text,
    embed_prompt,
    schedule_prompt_embedding,
)
from services.repositories.prompt_embedding_repository import PromptEmbeddingRepository


class _SessionScope:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


def _session():
    session = MagicMock()
    session.execute = AsyncMock()
    session.begin = MagicMock(return_value=session)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


class PromptEmbeddingTextTestCase(unittest.TestCase):
    def test_combines_title_description_and_content(self):
        text = build_prompt_embedding_text("議事録テンプレート", "会議メモを整理する", "以下のメモを整理してください。")

        self.assertIn("議事録テンプレート", text)
        self.assertIn("会議メモを整理する", text)
        self.assertIn("以下のメモを整理してください。", text)

    def test_skill_markdown_stands_in_for_an_empty_body(self):
        text = build_prompt_embedding_text("Skill", None, "", {"skill_markdown": "# Skill body"})

        self.assertIn("# Skill body", text)

    def test_content_wins_over_skill_markdown_when_present(self):
        text = build_prompt_embedding_text("Skill", None, "本文", {"skill_markdown": "# Skill body"})

        self.assertIn("本文", text)
        self.assertNotIn("# Skill body", text)

    def test_input_is_capped_to_the_provider_limit(self):
        text = build_prompt_embedding_text("t", None, "x" * 20000)

        self.assertLessEqual(len(text), prompt_embedding_service.EMBEDDING_MAX_INPUT_CHARS)


class PromptEmbeddingRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_store_guards_on_the_updated_at_the_text_was_read_with(self):
        session = _session()
        stamp = datetime(2026, 9, 24, 12, 0, 0)

        await PromptEmbeddingRepository(session).store(9, [0.1, 0.2], stamp)

        compiled = session.execute.await_args.args[0].compile(dialect=dialect())
        self.assertIn("UPDATE prompts", str(compiled))
        self.assertIn("prompts.updated_at = ", str(compiled))
        self.assertIn(9, compiled.params.values())
        self.assertIn(stamp, compiled.params.values())
        self.assertIn("ready", compiled.params.values())

    async def test_fetch_source_only_reads_live_public_prompts(self):
        session = _session()
        empty_result = MagicMock()
        empty_result.mappings.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=empty_result)

        source = await PromptEmbeddingRepository(session).fetch_source(9)

        self.assertIsNone(source)
        compiled = session.execute.await_args.args[0].compile(dialect=dialect())
        self.assertIn("prompts.is_public IS true", str(compiled))
        self.assertIn("prompts.deleted_at IS NULL", str(compiled))


class EmbedPromptTestCase(unittest.IsolatedAsyncioTestCase):
    def _patch_repository(self, source):
        repository = MagicMock()
        repository.fetch_source = AsyncMock(return_value=source)
        repository.store = AsyncMock()
        return repository

    async def test_reads_text_embeds_it_and_stores_under_the_row_guard(self):
        stamp = datetime(2026, 9, 24, 12, 0, 0)
        repository = self._patch_repository(
            {"title": "Title", "description": "Desc", "content": "Body", "attributes": {}, "updated_at": stamp}
        )
        with (
            patch.object(prompt_embedding_service, "session_scope", return_value=_SessionScope(_session())),
            patch.object(prompt_embedding_service, "PromptEmbeddingRepository", return_value=repository),
            patch.object(prompt_embedding_service, "generate_embedding", return_value=[0.5]) as generate,
        ):
            stored = await embed_prompt(7)

        self.assertTrue(stored)
        self.assertIn("Title", generate.call_args.args[0])
        repository.store.assert_awaited_once_with(7, [0.5], stamp)

    async def test_skips_prompts_that_are_gone_or_private(self):
        repository = self._patch_repository(None)
        with (
            patch.object(prompt_embedding_service, "session_scope", return_value=_SessionScope(_session())),
            patch.object(prompt_embedding_service, "PromptEmbeddingRepository", return_value=repository),
            patch.object(prompt_embedding_service, "generate_embedding") as generate,
        ):
            stored = await embed_prompt(7)

        self.assertFalse(stored)
        generate.assert_not_called()
        repository.store.assert_not_awaited()

    async def test_skips_storing_when_the_provider_returns_nothing(self):
        repository = self._patch_repository(
            {"title": "Title", "description": None, "content": "Body", "attributes": {}, "updated_at": None}
        )
        with (
            patch.object(prompt_embedding_service, "session_scope", return_value=_SessionScope(_session())),
            patch.object(prompt_embedding_service, "PromptEmbeddingRepository", return_value=repository),
            patch.object(prompt_embedding_service, "generate_embedding", return_value=None),
        ):
            stored = await embed_prompt(7)

        self.assertFalse(stored)
        repository.store.assert_not_awaited()


class PromptEmbeddingScheduleTestCase(unittest.TestCase):
    def test_skips_scheduling_when_embeddings_are_unavailable(self):
        with (
            patch.object(prompt_embedding_service, "embeddings_available", return_value=False),
            patch.object(prompt_embedding_service, "submit_background_task") as submit,
        ):
            schedule_prompt_embedding(1)

        submit.assert_not_called()

    def test_runs_the_embedding_off_the_request_path(self):
        embedded = []

        async def fake_embed(prompt_id):
            embedded.append(prompt_id)
            return True

        with (
            patch.object(prompt_embedding_service, "embeddings_available", return_value=True),
            patch.object(prompt_embedding_service, "embed_prompt", new=fake_embed),
            patch.object(prompt_embedding_service, "submit_background_task", side_effect=lambda task: task()),
        ):
            schedule_prompt_embedding(7)

        self.assertEqual(embedded, [7])


if __name__ == "__main__":
    unittest.main()
