from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import services.db as database


class AsyncEngineConfigurationTests(unittest.TestCase):
    def tearDown(self) -> None:
        database._engine = None
        database._session_factory = None

    def test_database_url_is_built_for_psycopg_three(self) -> None:
        with patch.dict(
            os.environ,
            {
                "POSTGRES_USER": "user",
                "POSTGRES_PASSWORD": "password",
                "POSTGRES_DB": "chatcore",
                "POSTGRES_HOST": "db",
                "POSTGRES_PORT": "5432",
            },
            clear=True,
        ):
            self.assertEqual(
                database.resolve_database_url(),
                "postgresql+psycopg://user:password@db:5432/chatcore",
            )

    def test_engine_has_a_bounded_async_pool(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://user:password@db/chatcore",
                "DB_POOL_MAX_CONN": "8",
                "DB_POOL_ACQUIRE_TIMEOUT_SECONDS": "4.5",
            },
            clear=True,
        ), patch("services.db.create_async_engine", return_value=object()) as create_engine:
            database.get_engine()

        kwargs = create_engine.call_args.kwargs
        self.assertEqual(kwargs["pool_size"], 8)
        self.assertEqual(kwargs["max_overflow"], 0)
        self.assertEqual(kwargs["pool_timeout"], 4.5)
        self.assertTrue(kwargs["pool_pre_ping"])


if __name__ == "__main__":
    unittest.main()
