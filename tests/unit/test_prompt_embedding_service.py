import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects.postgresql import dialect

from services import prompt_embedding_service
from services.prompt_embedding_service import (
    build_prompt_embedding_text,
    schedule_prompt_embedding,
    store_prompt_embedding,
)


class _SessionScope:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


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


class PromptEmbeddingStoreTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_store_marks_the_prompt_ready(self):
        session = MagicMock()
        session.execute = AsyncMock()
        session.begin = MagicMock(return_value=session)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch.object(prompt_embedding_service, "session_scope", return_value=_SessionScope(session)):
            await store_prompt_embedding(9, [0.1, 0.2])

        statement = session.execute.await_args.args[0]
        compiled = statement.compile(dialect=dialect())
        self.assertIn("UPDATE prompts", str(compiled))
        self.assertIn("embedding_status", str(compiled))
        self.assertIn(9, compiled.params.values())
        self.assertIn("ready", compiled.params.values())

    async def test_store_skips_empty_vectors(self):
        with patch.object(prompt_embedding_service, "session_scope") as scope:
            await store_prompt_embedding(9, [])

        scope.assert_not_called()


class PromptEmbeddingScheduleTestCase(unittest.TestCase):
    def test_skips_scheduling_when_embeddings_are_unavailable(self):
        with (
            patch.object(prompt_embedding_service, "embeddings_available", return_value=False),
            patch.object(prompt_embedding_service, "submit_background_task") as submit,
        ):
            schedule_prompt_embedding(1, "t", None, "c")

        submit.assert_not_called()

    def test_generates_and_stores_off_the_request_path(self):
        stored = []

        async def fake_store(prompt_id, embedding):
            stored.append((prompt_id, embedding))

        with (
            patch.object(prompt_embedding_service, "embeddings_available", return_value=True),
            patch.object(prompt_embedding_service, "generate_embedding", return_value=[0.5]) as generate,
            patch.object(prompt_embedding_service, "store_prompt_embedding", new=fake_store),
            patch.object(prompt_embedding_service, "submit_background_task", side_effect=lambda task: task()),
        ):
            schedule_prompt_embedding(7, "Title", "Desc", "Body")

        self.assertIn("Title", generate.call_args.args[0])
        self.assertEqual(stored, [(7, [0.5])])


if __name__ == "__main__":
    unittest.main()
