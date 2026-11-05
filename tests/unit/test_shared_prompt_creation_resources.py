"""共有プロンプトの作成（services.shared_prompt_service.create_shared_prompt）が、プロンプト本体とスキルのリソースを同一トランザクションで保存することを検証するテスト。
埋め込み生成の予約と、挿入失敗時のロールバックも確かめる。

Tests that create_shared_prompt (services.shared_prompt_service) saves the prompt and its skill resources in one transaction,
schedules embedding generation, and rolls back when an insert fails.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from services import shared_prompt_service
from services.request_models import SharedPromptCreateRequest
from services.shared_prompt_service import create_shared_prompt


# create_prompt の呼び出しを記録するプロンプトリポジトリの代役。
# Stand-in prompt repository that records create_prompt calls.
class RecordingPromptRepository:
    def __init__(self, prompt_id=42):
        self.prompt_id = prompt_id
        self.calls = []

    async def create_prompt(self, session, **kwargs):
        self.calls.append((session, kwargs))
        return self.prompt_id


# insert_many の呼び出しを記録し、指定されたエラーを送出できるリソースリポジトリの代役。
# Stand-in resource repository that records insert_many calls and can raise a given error.
class RecordingResourceRepository:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def insert_many(self, session, prompt_id, resources):
        self.calls.append((session, prompt_id, list(resources)))
        if self.error:
            raise self.error


# プロンプトとリソースの保存順、埋め込みの予約、失敗時のロールバックを検証するテストクラス。
# Test class for the save order of prompt and resources, embedding scheduling, and rollback on failure.
class SharedPromptCreationResourcesTestCase(unittest.TestCase):
    def _payload(self):
        return SharedPromptCreateRequest.model_validate(
            {
                "title": "Portable skill",
                "description": "A reusable portable skill.",
                "content_format": "skill",
                "attributes": {
                    "skill_markdown": "# Portable skill",
                    "skill_python_script": "print('legacy')",
                },
                "resources": [
                    {
                        "path": "scripts/run.ts",
                        "role": "script",
                        "language": "typescript",
                        "content": "export const run = () => true;",
                    }
                ],
            }
        )

    def test_saves_prompt_and_resources_with_one_async_transaction(self):
        session = AsyncMock()
        prompt_repository = RecordingPromptRepository()
        resource_repository = RecordingResourceRepository()

        prompt_id = asyncio.run(
            create_shared_prompt(
                7,
                self._payload(),
                repository=prompt_repository,
                resource_repository=resource_repository,
                session=session,
            )
        )

        self.assertEqual(prompt_id, 42)
        session.commit.assert_not_awaited()
        session.rollback.assert_not_awaited()
        self.assertEqual(resource_repository.calls[0][0], session)
        self.assertEqual(resource_repository.calls[0][1], 42)
        self.assertEqual(
            [item.path for item in resource_repository.calls[0][2]],
            ["scripts/run.ts", "scripts/main.py"],
        )
        self.assertEqual(
            prompt_repository.calls[0][1]["attributes"],
            {"skill_markdown": "# Portable skill"},
        )
        self.assertEqual(prompt_repository.calls[0][1]["description"], "A reusable portable skill.")

    def test_schedules_embedding_for_the_new_prompt(self):
        prompt_repository = RecordingPromptRepository(prompt_id=42)
        with patch.object(shared_prompt_service, "schedule_prompt_embedding") as schedule:
            asyncio.run(
                create_shared_prompt(
                    7,
                    self._payload(),
                    repository=prompt_repository,
                    resource_repository=RecordingResourceRepository(),
                    session=AsyncMock(),
                )
            )

        schedule.assert_called_once_with(42)

    def test_skips_embedding_when_the_insert_fails(self):
        with (
            patch.object(shared_prompt_service, "schedule_prompt_embedding") as schedule,
            self.assertRaises(RuntimeError),
        ):
            asyncio.run(
                create_shared_prompt(
                    7,
                    self._payload(),
                    repository=RecordingPromptRepository(),
                    resource_repository=RecordingResourceRepository(error=RuntimeError("insert failed")),
                    session=AsyncMock(),
                )
            )

        schedule.assert_not_called()

    def test_rolls_back_when_resource_insert_fails(self):
        session = AsyncMock()
        prompt_repository = RecordingPromptRepository()
        resource_repository = RecordingResourceRepository(error=RuntimeError("insert failed"))

        with self.assertRaises(RuntimeError):
            asyncio.run(
                create_shared_prompt(
                    7,
                    self._payload(),
                    repository=prompt_repository,
                    resource_repository=resource_repository,
                    session=session,
                )
            )

        session.commit.assert_not_awaited()
        session.rollback.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
