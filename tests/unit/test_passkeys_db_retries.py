import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

from services.passkeys import update_passkey_usage
from services.repositories.passkey_repository import PasskeyRepository


class RetryableDeadlockError(Exception):
    sqlstate = "40P01"


class PasskeyDbRetryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_repository_does_not_rollback_a_caller_owned_session(self):
        session = Mock()
        session.execute = AsyncMock(side_effect=RetryableDeadlockError())
        session.rollback = AsyncMock()
        repository = PasskeyRepository(session)

        with self.assertRaises(RetryableDeadlockError):
            await repository.update_usage(
                passkey_id=123,
                sign_count=9,
                credential_backed_up=True,
                credential_device_type="multiDevice",
            )

        session.rollback.assert_not_awaited()

    async def test_service_retries_owned_session_and_commits_only_after_success(self):
        sessions = [Mock(), Mock()]
        for session in sessions:
            session.commit = AsyncMock()
        repositories = [Mock(), Mock()]
        repositories[0].update_usage = AsyncMock(side_effect=RetryableDeadlockError())
        repositories[1].update_usage = AsyncMock()

        @asynccontextmanager
        async def scope(session):
            yield session

        with (
            patch("services.passkeys.PasskeyRepository", side_effect=repositories),
            patch(
                "services.passkeys.session_scope",
                side_effect=[scope(sessions[0]), scope(sessions[1])],
            ),
            patch("services.passkeys.is_retryable_db_error", return_value=True),
            patch("services.passkeys.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            await update_passkey_usage(
                123,
                9,
                credential_backed_up=True,
                credential_device_type="multiDevice",
            )

        repositories[0].update_usage.assert_awaited_once()
        repositories[1].update_usage.assert_awaited_once()
        sleep.assert_awaited_once()
        sessions[0].commit.assert_not_awaited()
        sessions[1].commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
