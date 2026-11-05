"""ヘルスチェック（liveness と readiness）が、DB・Redis・埋め込みの状態に応じて ok / degraded / error を返すことを検証するテスト。

Tests that the liveness and readiness checks report ok, degraded or error depending on the database, Redis and embeddings.
"""

import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from services.health import get_liveness_status, get_readiness_status


# readiness の DB 疎通確認に使う、常に 1 を返す非同期セッションの代役。
# Async session stand-in for the readiness database ping; it always returns 1.
class _AsyncSession:
    async def scalar(self, _statement):
        return 1


@asynccontextmanager
async def _session_scope():
    yield _AsyncSession()


# 必須の依存（DB）が落ちると error、任意の依存（Redis・埋め込み）が落ちると degraded になる区別を確かめる。
# Checks that a missing required dependency (database) gives error while optional ones (Redis, embeddings) only give degraded.
class HealthServiceTestCase(unittest.TestCase):
    def test_liveness_status_is_ok(self):
        self.assertEqual(get_liveness_status(), {"status": "ok"})

    def test_readiness_is_ok_when_dependencies_are_available(self):
        with (
            patch("services.health.session_scope", new=_session_scope),
            patch("services.health.is_redis_configured", return_value=True),
            patch("services.health.get_redis_client", return_value=object()),
        ):
            payload, status_code = asyncio.run(get_readiness_status())

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["components"]["database"]["status"], "ok")
        self.assertEqual(payload["components"]["redis"]["status"], "ok")

    def test_readiness_is_degraded_when_optional_redis_is_unavailable(self):
        with (
            patch("services.health.session_scope", new=_session_scope),
            patch("services.health.is_redis_configured", return_value=True),
            patch("services.health.get_redis_client", return_value=None),
        ):
            payload, status_code = asyncio.run(get_readiness_status())

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["components"]["redis"]["status"], "degraded")

    def test_readiness_is_degraded_when_embeddings_are_failing(self):
        failing_embeddings = {
            "status": "error",
            "required": False,
            "model": "text-embedding-3-small",
            "dimensions": 768,
            "consecutive_failures": 3,
        }
        with (
            patch("services.health.session_scope", new=_session_scope),
            patch("services.health.is_redis_configured", return_value=False),
            patch("services.health.get_embedding_health", return_value=failing_embeddings),
        ):
            payload, status_code = asyncio.run(get_readiness_status())

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["components"]["embeddings"]["status"], "error")

    def test_readiness_is_error_when_database_is_unavailable(self):
        async def raise_database_error():
            raise RuntimeError("db down")

        @asynccontextmanager
        async def failing_scope():
            await raise_database_error()
            yield

        with (
            patch("services.health.session_scope", new=failing_scope),
            patch("services.health.is_redis_configured", return_value=False),
        ):
            payload, status_code = asyncio.run(get_readiness_status())

        self.assertEqual(status_code, 503)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["components"]["database"]["status"], "error")


if __name__ == "__main__":
    unittest.main()
