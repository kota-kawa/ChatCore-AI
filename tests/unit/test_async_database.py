from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import services.db as database


class _FakeSession:
    def __init__(self) -> None:
        self.rolled_back = 0
        self.closed = 0
        self.active = True

    def in_transaction(self) -> bool:
        return self.active

    async def rollback(self) -> None:
        self.rolled_back += 1
        self.active = False

    async def close(self) -> None:
        self.closed += 1


class AsyncDatabaseTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        database._engine = None
        database._session_factory = None

    def test_resolve_database_url_uses_psycopg_async_driver(self) -> None:
        with patch.dict(
            os.environ,
            {
                "POSTGRES_USER": "db-user",
                "POSTGRES_PASSWORD": "db-password",
                "POSTGRES_DB": "chatcore",
                "POSTGRES_HOST": "db",
                "POSTGRES_PORT": "5432",
            },
            clear=True,
        ):
            self.assertEqual(
                database.resolve_database_url(),
                "postgresql+psycopg://db-user:db-password@db:5432/chatcore",
            )

    def test_engine_uses_bounded_async_pool(self) -> None:
        fake_engine = object()
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://user:password@db/chatcore",
                "DB_POOL_MAX_CONN": "7",
                "DB_POOL_ACQUIRE_TIMEOUT_SECONDS": "3.5",
            },
            clear=True,
        ), patch("services.db.create_async_engine", return_value=fake_engine) as create_engine:
            database.get_engine()

        create_engine.assert_called_once()
        kwargs = create_engine.call_args.kwargs
        self.assertEqual(kwargs["pool_size"], 7)
        self.assertEqual(kwargs["max_overflow"], 0)
        self.assertEqual(kwargs["pool_timeout"], 3.5)
        self.assertTrue(kwargs["pool_pre_ping"])

    async def test_session_scope_rolls_back_and_closes_on_error(self) -> None:
        fake_session = _FakeSession()

        def factory():
            return fake_session

        with patch("services.db.get_session_factory", return_value=factory):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                async with database.session_scope():
                    raise RuntimeError("boom")

        self.assertEqual(fake_session.rolled_back, 1)
        self.assertEqual(fake_session.closed, 1)


if __name__ == "__main__":
    unittest.main()
