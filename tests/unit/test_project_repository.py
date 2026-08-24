import unittest
from unittest.mock import AsyncMock

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.repositories.project_repository import ProjectRepository


class ProjectRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = ProjectRepository(object())

    async def test_create_project_delegates_to_async_chat_repository(self):
        expected = {"id": 7, "name": "リサーチ", "instructions": "丁寧に"}
        self.repo._chat_repository.create_project = AsyncMock(return_value=expected)

        result = await self.repo.create_project(1, "リサーチ", "丁寧に")

        self.assertIs(result, expected)
        self.repo._chat_repository.create_project.assert_awaited_once_with(1, "リサーチ", "丁寧に")

    async def test_project_reads_are_awaited(self):
        expected = {"id": 5, "name": "P", "rooms": []}
        self.repo._chat_repository.get_project = AsyncMock(return_value=expected)
        self.repo._chat_repository.list_projects = AsyncMock(return_value=[expected])

        self.assertIs(await self.repo.get_project(5, 1), expected)
        self.assertEqual(await self.repo.list_projects(1), [expected])
        self.repo._chat_repository.get_project.assert_awaited_once_with(5, 1)
        self.repo._chat_repository.list_projects.assert_awaited_once_with(1)

    async def test_ownership_errors_are_propagated(self):
        error = ForbiddenOperationError("他ユーザーのプロジェクトは操作できません")
        self.repo._chat_repository.delete_project = AsyncMock(side_effect=error)

        with self.assertRaises(ForbiddenOperationError):
            await self.repo.delete_project(5, 1)

    async def test_missing_project_errors_are_propagated(self):
        error = ResourceNotFoundError("該当プロジェクトが見つかりません")
        self.repo._chat_repository.get_project_context = AsyncMock(side_effect=error)

        with self.assertRaises(ResourceNotFoundError):
            await self.repo.get_project_context("room-1")

    async def test_room_assignment_and_room_listing_use_async_api(self):
        self.repo._chat_repository.assign_room_to_project = AsyncMock()
        expected_rooms = [{"id": "room-1", "mode": "normal"}]
        self.repo._chat_repository.list_project_rooms = AsyncMock(return_value=expected_rooms)

        await self.repo.assign_room_to_project("room-1", 1, 5)
        result = await self.repo.list_project_rooms(5, 1)

        self.repo._chat_repository.assign_room_to_project.assert_awaited_once_with("room-1", 1, 5)
        self.assertIs(result, expected_rooms)


if __name__ == "__main__":
    unittest.main()
