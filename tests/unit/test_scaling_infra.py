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
