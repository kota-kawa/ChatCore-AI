"""プロンプトの埋め込み生成（services.prompt_embedding_service）を検証するテスト。
埋め込み用テキストの組み立て、更新時刻による保存ガード、生成から保存までの流れ、リクエスト外での実行予約を確かめる。

Tests for prompt embedding generation (services.prompt_embedding_service): embedding-text building, the updated_at write guard,
the read-embed-store flow, and scheduling the work off the request path.
"""

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


# DB セッションを非同期コンテキストとして返すだけのテスト用スコープ。
# Test scope that simply yields a DB session as an async context manager.
class _SessionScope:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


# begin / execute を持つ非同期セッションのモックを作る補助関数。
# Helper that builds a mock async session with begin / execute.
def _session():
    session = MagicMock()
    session.execute = AsyncMock()
    session.begin = MagicMock(return_value=session)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


# 埋め込み対象テキスト（題名・説明・本文・スキル本文）の組み立てと長さ制限を検証するテストクラス。
# Test class for building embedding text from title, description, body and skill markdown, and for its length cap.
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


# 埋め込みリポジトリの保存ガードと、公開中のプロンプトだけを読むことを検証するテストクラス。
# Test class for the embedding repository's write guard and its reading of only live public prompts.
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


# embed_prompt の読み取り・生成・保存の流れと、スキップ条件を検証するテストクラス。
# Test class for embed_prompt's read, embed and store flow and its skip conditions.
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


# 埋め込み生成の実行予約（不可なら予約しない、リクエスト経路の外で実行）を検証するテストクラス。
# Test class for scheduling embedding work: skipped when unavailable, and run off the request path.
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
