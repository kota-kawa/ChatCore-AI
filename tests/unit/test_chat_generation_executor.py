"""生成ジョブ専用プールの容量制御を検証するテスト。

Tests for the admission control in front of the generation-only thread pool.
"""

import io
import logging
import os
import threading
import time
import unittest
from unittest.mock import patch

from services.chat_generation_executor import ChatGenerationCapacityError, _GenerationExecutor
from services.logging_config import JsonLogFormatter
from services.request_context import RequestContextFilter, _request_id_var


class ChatGenerationExecutorCapacityTestCase(unittest.TestCase):
    # 日本語: テストごとに独立したプールを使い、環境変数の変更が他テストへ漏れないようにする。
    # English: Use a fresh pool per test so an environment override never leaks into another test.
    def setUp(self):
        self.executor = _GenerationExecutor()

    def tearDown(self):
        self.executor.shutdown(wait=True, cancel_futures=True)

    # 日本語: CHAT_GENERATION_WORKER_THREADS の値が同時実行数の上限として読まれることを確認する。
    # English: Verify CHAT_GENERATION_WORKER_THREADS is read as the concurrency ceiling.
    def test_capacity_is_read_from_environment(self):
        with patch.dict(os.environ, {"CHAT_GENERATION_WORKER_THREADS": "3"}):
            self.assertEqual(self.executor.capacity(), 3)

    # 日本語: 空き枠が無いとき、新しいジョブはキューへ積まれず即座に拒否されることを確認する。
    # 8スレッド共有プールの「9本目が無言で滞留する」問題を、拒否という形で可視化する。
    # English: Verify a job with no free slot is rejected immediately instead of being queued.
    # This turns the old "ninth job silently stalls on the shared 8-thread pool" failure into
    # a loud rejection.
    def test_a_job_beyond_capacity_is_rejected_instead_of_queued(self):
        with patch.dict(os.environ, {"CHAT_GENERATION_WORKER_THREADS": "2"}):
            release = threading.Event()
            # 2つのワーカースレッドと本スレッドがそろって初めて先へ進むバリア。
            # これで「2枠とも本当に埋まっている」ことを保証してから容量確認を行える。
            # A barrier that releases only once both worker threads and this thread arrive,
            # guaranteeing both slots are genuinely occupied before checking capacity.
            both_started = threading.Barrier(3, timeout=5)

            def _blocking_job():
                both_started.wait(timeout=5)
                release.wait(timeout=5)

            self.executor.submit(_blocking_job)
            self.executor.submit(_blocking_job)
            both_started.wait(timeout=5)

            self.assertEqual(self.executor.in_flight(), 2)
            with self.assertRaises(ChatGenerationCapacityError):
                self.executor.submit(_blocking_job)

            release.set()
            deadline = time.monotonic() + 5
            while self.executor.in_flight() != 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(self.executor.in_flight(), 0)

    # 日本語: 実行中ジョブが完了して枠が空けば、直後の投入は成功することを確認する。
    # English: Verify a slot freed by a finished job can immediately admit a new submission.
    def test_a_freed_slot_admits_the_next_job(self):
        with patch.dict(os.environ, {"CHAT_GENERATION_WORKER_THREADS": "1"}):
            future = self.executor.submit(lambda: "first")
            self.assertEqual(future.result(timeout=5), "first")

            deadline = time.monotonic() + 5
            while self.executor.in_flight() != 0 and time.monotonic() < deadline:
                time.sleep(0.01)

            second = self.executor.submit(lambda: "second")
            self.assertEqual(second.result(timeout=5), "second")

    # 日本語: 投入に失敗した場合でも in_flight のカウントが残らないことを確認する。
    # English: Verify the in-flight count is not left incremented when submission itself fails.
    def test_in_flight_count_is_restored_when_the_underlying_submit_fails(self):
        with patch.dict(os.environ, {"CHAT_GENERATION_WORKER_THREADS": "2"}):
            self.executor.get()  # プールを遅延初期化しておく / force lazy pool creation
            with patch.object(
                self.executor._executor,
                "submit",
                side_effect=RuntimeError("cannot schedule new futures"),
            ):
                with self.assertRaises(RuntimeError):
                    self.executor.submit(lambda: None)
            self.assertEqual(self.executor.in_flight(), 0)


    # 日本語: 生成ジョブのログが、投入元のリクエストIDを保ったまま出ることを確認する。
    # English: Verify a generation job's log lines keep the request id of the submitting request.
    def test_a_job_keeps_the_request_context_of_its_submitter(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonLogFormatter())
        handler.addFilter(RequestContextFilter())
        logger = logging.getLogger("tests.chat_generation_executor.request_context")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

        token = _request_id_var.set("req-from-the-http-layer")
        try:
            self.executor.submit(lambda: logger.info("generation log line")).result(timeout=5)
        finally:
            _request_id_var.reset(token)
            logger.removeHandler(handler)

        self.assertIn('"request_id": "req-from-the-http-layer"', stream.getvalue())


if __name__ == "__main__":
    unittest.main()
