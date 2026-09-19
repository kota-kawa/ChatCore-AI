"""生成ジョブ専用のスレッドプールと、その空き枠の管理を担うモジュール。

Owns the thread pool dedicated to chat generation jobs and the admission control in front
of it.

生成ジョブは1ターンあたり数分スレッドを占有するため、記憶抽出やメモ埋め込みのような
短命なバックグラウンド処理と同じプールに置くと、後者の既定8スレッドを食い尽くして
9本目以降が無言でキューに滞留する。SSE 側（`services/async_utils.py` の
`SSE_STREAM_MAX_WORKERS`）は同時接続を 256 まで受け入れるので、生成側の上限もそこへ
揃えたうえで、空き枠が無いときは黙って待たせず明示的に拒否する。
A generation job holds its thread for the whole turn, so sharing the short-lived background
pool (default eight threads) let the ninth caller queue silently while the API reported the
turn as running. This pool is sized to match the SSE ceiling instead, and refuses admission
loudly once every slot is taken rather than queueing without a signal.
"""

from __future__ import annotations

import atexit
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, TypeVar

from services.env_settings import env_int

logger = logging.getLogger(__name__)

T = TypeVar("T")

# SSE 受け入れ上限（`SSE_STREAM_MAX_WORKERS` の既定値）と揃えた同時生成数の既定値。
# Default concurrency, kept in step with the SSE acceptance ceiling.
DEFAULT_GENERATION_WORKER_THREADS = 256


# 生成スロットが空いていないことを表す例外。呼び出し側は 503 相当で返す。
# Raised when no generation slot is free; callers surface it as a 503-style response.
class ChatGenerationCapacityError(RuntimeError):
    pass


# 生成ジョブ専用プールと、その使用中スロット数を保持するシングルトン。
# Singleton holding the generation-only pool and the number of slots currently in use.
class _GenerationExecutor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._capacity = 0
        self._in_flight = 0

    # プールと同時実行上限を遅延初期化する（ロック保持中に呼ぶこと）。
    # Lazily create the pool and resolve its ceiling; call while holding the lock.
    def _ensure_executor_locked(self) -> ThreadPoolExecutor:
        if self._executor is None:
            self._capacity = env_int(
                "CHAT_GENERATION_WORKER_THREADS",
                DEFAULT_GENERATION_WORKER_THREADS,
            )
            self._executor = ThreadPoolExecutor(
                max_workers=self._capacity,
                thread_name_prefix="chat-core-generation",
            )
        return self._executor

    def get(self) -> ThreadPoolExecutor:
        with self._lock:
            return self._ensure_executor_locked()

    def capacity(self) -> int:
        with self._lock:
            self._ensure_executor_locked()
            return self._capacity

    def in_flight(self) -> int:
        with self._lock:
            return self._in_flight

    # 空き枠を確保してからジョブを投入する。枠が無ければキューへ積まずに拒否する。
    # Take a slot before submitting; with none free the job is refused, never queued.
    def submit(self, func: Any, *args: Any, **kwargs: Any) -> Future[T]:
        with self._lock:
            executor = self._ensure_executor_locked()
            if self._in_flight >= self._capacity:
                raise ChatGenerationCapacityError(
                    f"All {self._capacity} chat generation slots are busy."
                )
            self._in_flight += 1

        def _release(_future: Future[Any]) -> None:
            with self._lock:
                self._in_flight = max(self._in_flight - 1, 0)

        try:
            future: Future[T] = executor.submit(func, *args, **kwargs)
        except BaseException:
            with self._lock:
                self._in_flight = max(self._in_flight - 1, 0)
            raise
        future.add_done_callback(_release)
        return future

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        with self._lock:
            executor = self._executor
            self._executor = None
            self._in_flight = 0
        if executor is None:
            return
        executor.shutdown(wait=wait, cancel_futures=cancel_futures)


_generation_executor = _GenerationExecutor()


# 生成ジョブ専用のエグゼキュータを取得する（スレッドセーフな遅延初期化）
# Get the generation-only executor (thread-safe lazy initialization).
def get_generation_executor() -> ThreadPoolExecutor:
    return _generation_executor.get()


# 生成ジョブを専用プールへ投入する。空き枠が無ければ ChatGenerationCapacityError を送出する。
# Submit a generation job to the dedicated pool, raising ChatGenerationCapacityError when full.
def submit_generation_task(func: Any, *args: Any, **kwargs: Any) -> Future[T]:
    return _generation_executor.submit(func, *args, **kwargs)


# 同時に実行できる生成ジョブ数を返す
# Return how many generation jobs may run at once.
def generation_capacity() -> int:
    return _generation_executor.capacity()


# 現在スロットを占有している生成ジョブ数を返す
# Return how many generation jobs currently hold a slot.
def generation_in_flight() -> int:
    return _generation_executor.in_flight()


# 生成ジョブ専用のエグゼキュータをシャットダウンする
# Shut down the generation-only executor.
def shutdown_generation_executor(
    *,
    wait: bool = True,
    cancel_futures: bool = False,
) -> None:
    _generation_executor.shutdown(wait=wait, cancel_futures=cancel_futures)


# プロセス終了時に自動でシャットダウンを実行するよう登録
# Register the shutdown handler to be called automatically on process exit.
atexit.register(shutdown_generation_executor)
