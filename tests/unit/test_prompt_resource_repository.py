import unittest
from unittest.mock import AsyncMock, MagicMock

from services.models import PromptResource
from services.repositories.prompt_resource_repository import PromptResourceRepository
from services.request_models import SkillResourceInput


class _ScalarResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values

    def scalar_one_or_none(self):
        return self._values[0] if self._values else None


class PromptResourceRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_insert_many_uses_orm_and_preserves_digest_order(self):
        session = AsyncMock()
        session.add_all = MagicMock()
        repository = PromptResourceRepository()
        resources = [
            SkillResourceInput(path="scripts/a.py", role="script", content="あ"),
            SkillResourceInput(path="references/a.md", role="reference", content="# A"),
        ]

        await repository.insert_many(session, 9, resources)

        rows = session.add_all.call_args.args[0]
        self.assertEqual(len(rows), 2)
        self.assertIsInstance(rows[0], PromptResource)
        self.assertEqual(rows[0].prompt_id, 9)
        self.assertEqual(rows[0].size_bytes, 3)
        self.assertEqual(rows[0].sort_order, 0)
        self.assertEqual(rows[1].sort_order, 1)
        session.flush.assert_awaited_once()

    async def test_replace_deletes_then_inserts_inside_same_session(self):
        session = AsyncMock()
        session.add_all = MagicMock()
        repository = PromptResourceRepository()
        resource = SkillResourceInput(path="config/settings.json", role="config", content="{}")

        await repository.replace_for_prompt(session, 5, [resource])

        session.execute.assert_awaited_once()
        self.assertEqual(session.add_all.call_args.args[0][0].prompt_id, 5)
        session.flush.assert_awaited_once()

    async def test_list_and_get_map_text_content_to_public_content_key(self):
        first = PromptResource(id=1, prompt_id=3, path="scripts/run.py", role="script", text_content="print(1)", language="python", media_type="text/x-python", size_bytes=8, sort_order=0)
        session = AsyncMock()
        session.execute.side_effect = [_ScalarResult([first]), _ScalarResult([first])]
        repository = PromptResourceRepository()

        listed = await repository.list_for_prompt(session, 3)
        fetched = await repository.get_for_prompt(session, 3, "SCRIPTS/run.py")

        self.assertEqual(listed[0]["content"], "print(1)")
        self.assertEqual(fetched["path"], "scripts/run.py")
        self.assertEqual(session.execute.await_count, 2)


if __name__ == "__main__":
    unittest.main()
