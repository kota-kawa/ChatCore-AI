import asyncio
import unittest
from unittest.mock import patch

from services import async_utils, cache, db


# 接続プールの待機リトライ／タイムアウト挙動を検証するテスト。
# Tests for the connection pool bounded-wait retry / timeout behavior.
class DbPoolAcquireTestCase(unittest.TestCase):
    # 枯渇 PoolError の後に成功すれば、待機リトライして接続を返すこと。
    # A transient exhausted PoolError should be retried until a connection is returned.
    def test_get_db_connection_retries_until_available(self):
        attempts = {"count": 0}

        class DummyConn:
            class _DummyCursor:
                def execute(self, *args, **kwargs): pass
                def __enter__(self): return self
                def __exit__(self, *args): pass
            def cursor(self): return self._DummyCursor()
            closed = 0

        class FakePool:
            def getconn(self):
                attempts["count"] += 1
                if attempts["count"] < 3:
                    raise db.PoolError("connection pool exhausted")
                return DummyConn()

            def putconn(self, *_args, **_kwargs):
                pass

        with patch.object(db, "_get_connection_pool", return_value=FakePool()):
            with patch.dict(
                "os.environ",
                {
                    "DB_POOL_ACQUIRE_TIMEOUT_SECONDS": "5",
                    "DB_POOL_ACQUIRE_RETRY_INTERVAL_SECONDS": "0.001",
                },
            ):
                conn = db.get_db_connection()

        self.assertIsNotNone(conn)
        self.assertEqual(attempts["count"], 3)

    # 枯渇が継続したら、タイムアウト後に DbConnectionPoolTimeout を送出すること。
    # Persistent exhaustion should raise DbConnectionPoolTimeout once the deadline passes.
    def test_get_db_connection_times_out_when_pool_stays_exhausted(self):
        class AlwaysExhaustedPool:
            def getconn(self):
                raise db.PoolError("connection pool exhausted")

        with patch.object(db, "_get_connection_pool", return_value=AlwaysExhaustedPool()):
            with patch.dict(
                "os.environ",
                {
                    "DB_POOL_ACQUIRE_TIMEOUT_SECONDS": "0.05",
                    "DB_POOL_ACQUIRE_RETRY_INTERVAL_SECONDS": "0.001",
                },
            ):
                with self.assertRaises(db.DbConnectionPoolTimeout):
                    db.get_db_connection()

    # 枯渇以外の PoolError はリトライせずそのまま伝播すること。
    # A non-exhaustion PoolError must propagate immediately without retrying.
    def test_get_db_connection_propagates_non_exhaustion_pool_error(self):
        class BadPool:
            def getconn(self):
                raise db.PoolError("trying to put unkeyed connection")

        with patch.object(db, "_get_connection_pool", return_value=BadPool()):
            with self.assertRaises(db.PoolError):
                db.get_db_connection()


# シングルフライトロックと TTL キャッシュのヘルパーを検証するテスト。
# Tests for the single-flight lock and TTL cache helpers.
class CacheHelpersTestCase(unittest.TestCase):
    # Redis 未設定時はフェイルオープンして True を返すこと。
    # When Redis is unavailable the lock fails open and returns True.
    def test_single_flight_fails_open_without_redis(self):
        with patch.object(cache, "get_redis_client", return_value=None):
            self.assertTrue(cache.try_acquire_single_flight("job", 60))

    # Redis 上では最初の獲得者のみ True、以降は False を返すこと。
    # On Redis only the first caller wins the lock; later callers get False.
    def test_single_flight_grants_lock_once(self):
        store: dict[str, str] = {}

        class FakeRedis:
            def set(self, key, value, nx=False, ex=None):
                if nx and key in store:
                    return None
                store[key] = value
                return True

        with patch.object(cache, "get_redis_client", return_value=FakeRedis()):
            self.assertTrue(cache.try_acquire_single_flight("job", 60))
            self.assertFalse(cache.try_acquire_single_flight("job", 60))

    # JSON キャッシュの set / get がラウンドトリップすること。
    # The JSON cache set/get round-trips a value.
    def test_cache_json_round_trip(self):
        store: dict[str, str] = {}

        class FakeRedis:
            def set(self, key, value, ex=None):
                store[key] = value
                return True

            def get(self, key):
                return store.get(key)

        payload = [{"name": "a"}, {"name": "b"}]
        with patch.object(cache, "get_redis_client", return_value=FakeRedis()):
            cache.cache_set_json("k", payload, 30)
            self.assertEqual(cache.cache_get_json("k"), payload)

    # キャッシュミス時は None を返すこと。
    # A cache miss returns None.
    def test_cache_get_json_miss_returns_none(self):
        class FakeRedis:
            def get(self, key):
                return None

        with patch.object(cache, "get_redis_client", return_value=FakeRedis()):
            self.assertIsNone(cache.cache_get_json("missing"))


# 専用ブロッキングエグゼキュータ経由で run_blocking が動作することを検証するテスト。
# Tests that run_blocking executes via the dedicated blocking executor.
class RunBlockingTestCase(unittest.TestCase):
    def test_run_blocking_executes_in_thread_pool(self):
        def add(a, b):
            return a + b

        result = asyncio.run(async_utils.run_blocking(add, 2, 3))
        self.assertEqual(result, 5)

    def test_run_blocking_passes_kwargs(self):
        def join(*parts, sep="-"):
            return sep.join(parts)

        result = asyncio.run(async_utils.run_blocking(join, "a", "b", sep="/"))
        self.assertEqual(result, "a/b")


if __name__ == "__main__":
    unittest.main()
