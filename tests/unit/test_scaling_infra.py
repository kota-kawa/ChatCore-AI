"""スケールアウト向けの補助（services.cache の single-flight ロック、services.async_utils の run_blocking）を検証するテスト。

Tests for scale-out helpers: the single-flight lock in services.cache and run_blocking in services.async_utils.
"""

import asyncio
import unittest
from unittest.mock import patch

from services import async_utils, cache


# Redis が無いときはロックを通し（フェイルオープン）、ある場合は 1 度だけ取得できることを検証するテストクラス。
# Test class verifying the lock fails open without Redis and is granted only once when Redis is present.
class CacheHelpersTestCase(unittest.TestCase):
    def test_single_flight_fails_open_without_redis(self):
        with patch.object(cache, "get_redis_client", return_value=None):
            self.assertTrue(cache.try_acquire_single_flight("job", 60))

    def test_single_flight_grants_lock_once(self):
        store: dict[str, str] = {}

        # SET NX だけを再現する Redis の代役。
        # Redis stand-in that only reproduces SET NX.
        class FakeRedis:
            def set(self, key, value, nx=False, ex=None):
                if nx and key in store:
                    return None
                store[key] = value
                return True

        with patch.object(cache, "get_redis_client", return_value=FakeRedis()):
            self.assertTrue(cache.try_acquire_single_flight("job", 60))
            self.assertFalse(cache.try_acquire_single_flight("job", 60))

# 同期処理を別スレッドで実行する run_blocking が結果と kwargs を正しく扱うことを検証するテストクラス。
# Test class verifying that run_blocking runs sync work off the event loop and handles results and kwargs.
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
