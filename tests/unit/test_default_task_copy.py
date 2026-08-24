import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

from services.users import copy_default_tasks_for_user


@asynccontextmanager
async def fake_session_scope(session):
    yield session


class DefaultTaskCopyTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_copy_uses_repository_transaction_boundary(self):
        session = Mock()
        session.commit = AsyncMock()
        repository = Mock()
        repository.copy_default_tasks = AsyncMock()

        with patch("services.users.UserRepository", return_value=repository), patch(
            "services.users.session_scope", return_value=fake_session_scope(session)
        ):
            await copy_default_tasks_for_user(7)

        repository.copy_default_tasks.assert_awaited_once_with(7)
        session.commit.assert_awaited_once()

    async def test_copy_rolls_back_when_repository_fails(self):
        session = Mock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        repository = Mock()
        repository.copy_default_tasks = AsyncMock(side_effect=RuntimeError("copy failed"))

        with patch("services.users.UserRepository", return_value=repository), patch(
            "services.users.session_scope", return_value=fake_session_scope(session)
        ):
            with self.assertRaises(RuntimeError):
                await copy_default_tasks_for_user(7)

        session.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
