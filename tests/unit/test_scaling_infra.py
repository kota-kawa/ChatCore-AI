import asyncio
import unittest
from unittest.mock import patch

from services import async_utils, cache


class CacheHelpersTestCase(unittest.TestCase):
    def test_single_flight_fails_open_without_redis(self):
        with patch.object(cache, "get_redis_client", return_value=None):
            self.assertTrue(cache.try_acquire_single_flight("job", 60))

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

    def test_cache_get_json_miss_returns_none(self):
        class FakeRedis:
            def get(self, key):
                return None

        with patch.object(cache, "get_redis_client", return_value=FakeRedis()):
            self.assertIsNone(cache.cache_get_json("missing"))


class RunBlockingTestCase(unittest.TestCase):
    def test_run_blocking_executes_non_database_work(self):
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
