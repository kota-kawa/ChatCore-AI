import unittest
from datetime import datetime
from unittest.mock import AsyncMock, Mock

from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect

from services.api_errors import ForbiddenOperationError, ResourceNotFoundError
from services.models import ChatRoom, Project
from services.repositories.project_repository import (
    MAX_PROJECT_INSTRUCTIONS_LENGTH,
    MAX_PROJECT_NAME_LENGTH,
    ProjectRepository,
)


def _compile(statement) -> str:
    return str(statement.compile(dialect=postgresql_dialect()))


def _project(**overrides) -> Project:
    values = {
        "id": 5,
        "user_id": 1,
        "name": "リサーチ",
        "instructions": "丁寧に",
        "created_at": datetime(2026, 9, 1, 12, 0, 0),
        "updated_at": datetime(2026, 9, 2, 12, 0, 0),
    }
    values.update(overrides)
    return Project(**values)


def _result(scalar_one_or_none=None) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = scalar_one_or_none
    return result


class ProjectRepositoryOwnershipTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_missing_project_raises_not_found(self):
        session = Mock()
        session.execute = AsyncMock(return_value=_result(None))

        with self.assertRaises(ResourceNotFoundError):
            await ProjectRepository(session).get_project(5, 1)

    async def test_other_users_project_raises_forbidden(self):
        session = Mock()
        session.execute = AsyncMock(return_value=_result(_project(user_id=99)))

        with self.assertRaises(ForbiddenOperationError):
            await ProjectRepository(session).get_project(5, 1)

    async def test_update_locks_the_project_row(self):
        session = Mock()
        session.execute = AsyncMock(return_value=_result(_project()))
        session.flush = AsyncMock()

        await ProjectRepository(session).update_project(5, 1, name="新しい名前")

        self.assertIn("FOR UPDATE", _compile(session.execute.await_args.args[0]))


class ProjectRepositoryPersistenceTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_create_project_normalizes_name_and_instructions(self):
        session = Mock()
        session.flush = AsyncMock()

        payload = await ProjectRepository(session).create_project(
            1,
            "  " + "あ" * (MAX_PROJECT_NAME_LENGTH + 10) + "  ",
            "い" * (MAX_PROJECT_INSTRUCTIONS_LENGTH + 10),
        )

        added = session.add.call_args.args[0]
        self.assertEqual(len(added.name), MAX_PROJECT_NAME_LENGTH)
        self.assertEqual(len(added.instructions), MAX_PROJECT_INSTRUCTIONS_LENGTH)
        self.assertEqual(payload["name"], added.name)

    async def test_blank_name_falls_back_to_the_default_title(self):
        session = Mock()
        session.flush = AsyncMock()

        await ProjectRepository(session).create_project(1, "   ")

        self.assertEqual(session.add.call_args.args[0].name, "新規プロジェクト")

    async def test_get_project_serializes_rooms_with_camel_case_timestamps(self):
        rooms_result = Mock()
        rooms_result.scalars.return_value.all.return_value = [
            ChatRoom(
                id="room-1",
                user_id=1,
                title="調査",
                mode="normal",
                created_at=datetime(2026, 9, 1, 12, 0, 0),
                last_activity_at=datetime(2026, 9, 3, 12, 0, 0),
            )
        ]
        session = Mock()
        session.execute = AsyncMock(side_effect=[_result(_project()), rooms_result])

        payload = await ProjectRepository(session).get_project(5, 1)

        self.assertEqual(payload["id"], 5)
        room = payload["rooms"][0]
        self.assertIn("createdAt", room)
        self.assertIn("lastActivityAt", room)
        self.assertNotIn("created_at", room)

    async def test_list_projects_reports_the_room_count(self):
        rows = Mock()
        rows.all.return_value = [(_project(), 3)]
        session = Mock()
        session.execute = AsyncMock(return_value=rows)

        projects = await ProjectRepository(session).list_projects(1)

        self.assertEqual(projects[0]["chatCount"], 3)


class ProjectRoomAssignmentTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_assignment_checks_room_and_project_ownership(self):
        session = Mock()
        session.execute = AsyncMock(
            side_effect=[
                _result(ChatRoom(id="room-1", user_id=1)),
                _result(_project()),
                Mock(),
            ]
        )

        await ProjectRepository(session).assign_room_to_project("room-1", 1, 5)

        self.assertIn("FOR UPDATE", _compile(session.execute.await_args_list[0].args[0]))
        self.assertIn("project_id=", _compile(session.execute.await_args_list[2].args[0]))

    async def test_assignment_rejects_a_room_owned_by_another_user(self):
        session = Mock()
        session.execute = AsyncMock(return_value=_result(ChatRoom(id="room-1", user_id=99)))

        with self.assertRaises(ForbiddenOperationError):
            await ProjectRepository(session).assign_room_to_project("room-1", 1, 5)

    async def test_clearing_the_project_skips_the_project_lookup(self):
        session = Mock()
        session.execute = AsyncMock(
            side_effect=[_result(ChatRoom(id="room-1", user_id=1)), Mock()]
        )

        await ProjectRepository(session).assign_room_to_project("room-1", 1, None)

        self.assertEqual(session.execute.await_count, 2)

    async def test_project_context_returns_none_without_a_project(self):
        rows = Mock()
        rows.one_or_none.return_value = None
        session = Mock()
        session.execute = AsyncMock(return_value=rows)

        self.assertIsNone(await ProjectRepository(session).get_project_context("room-1"))

    async def test_project_context_strips_instruction_whitespace(self):
        rows = Mock()
        rows.one_or_none.return_value = (5, "リサーチ", "  丁寧に  ")
        session = Mock()
        session.execute = AsyncMock(return_value=rows)

        context = await ProjectRepository(session).get_project_context("room-1")

        self.assertEqual(context, {"project_id": 5, "name": "リサーチ", "instructions": "丁寧に"})


if __name__ == "__main__":
    unittest.main()
