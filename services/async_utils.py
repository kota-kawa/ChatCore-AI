from __future__ import annotations

import asyncio
import atexit
import logging
import threading
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, TypeVar

from services.env_settings import env_int

logger = logging.getLogger(__name__)

T = TypeVar("T")

# DB以外のブロッキングI/O（外部HTTP・ファイル等）を逃がす専用スレッドプール。
# asyncio.to_thread の既定エグゼキュータ（プロセス共有・暗黙のサイズ）に依存せず、
# 1ワーカープロセスあたりの同時ブロッキング処理数を環境変数で明示制御する。
# Dedicated pool for non-database blocking I/O (outbound HTTP / files). Avoids relying on
# asyncio.to_thread's implicit shared default executor so the per-process concurrency
# budget for blocking work is explicit and tunable via the environment.
_DEFAULT_MAX_WORKERS = 64

# SSE ストリームのように「1接続が1スレッドを長時間占有する」処理は別プールへ分ける。
# 短命なブロッキングI/Oと同じプールに置くと、ストリームが増えただけで通常のDB・HTTP
# 呼び出しが待たされるため、上限を独立に設定できるようにする（無制限にはしない）。
# Long-lived offloads such as SSE streams hold a thread for the life of the connection, so
# they get their own pool. Sharing the short-lived blocking pool would let a burst of
# streams starve ordinary DB/HTTP calls. The ceiling stays explicit and bounded.
_DEFAULT_STREAM_MAX_WORKERS = 256


# 環境変数で上限を決める遅延初期化のシングルトンスレッドプール
# Lazily initialized singleton thread pool whose ceiling comes from the environment.
class _LazyExecutor:
    def __init__(
        self,
        *,
        resolve_max_workers: Callable[[], int],
        thread_name_prefix: str,
    ) -> None:
        self._resolve_max_workers = resolve_max_workers
        self._thread_name_prefix = thread_name_prefix
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None

    def get(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._resolve_max_workers(),
                    thread_name_prefix=self._thread_name_prefix,
                )
            return self._executor

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=wait)


def _resolve_max_workers() -> int:
    return env_int("RUN_BLOCKING_MAX_WORKERS", _DEFAULT_MAX_WORKERS)


def _resolve_stream_max_workers() -> int:
    return env_int("SSE_STREAM_MAX_WORKERS", _DEFAULT_STREAM_MAX_WORKERS)


_blocking_pool = _LazyExecutor(
    resolve_max_workers=_resolve_max_workers,
    thread_name_prefix="chat-core-blocking",
)
_stream_pool = _LazyExecutor(
    resolve_max_workers=_resolve_stream_max_workers,
    thread_name_prefix="chat-core-stream",
)


# シングルトンのブロッキング用エグゼキュータを取得する（スレッドセーフな遅延初期化）
# Get the singleton blocking-work executor (thread-safe lazy initialization).
def get_blocking_executor() -> ThreadPoolExecutor:
    return _blocking_pool.get()


# ストリーム反復用のシングルトンエグゼキュータを取得する（スレッドセーフな遅延初期化）
# Get the singleton stream-iteration executor (thread-safe lazy initialization).
def get_stream_executor() -> ThreadPoolExecutor:
    return _stream_pool.get()


# ブロッキング用エグゼキュータをシャットダウンする
# Shut down the blocking-work executor.
def shutdown_blocking_executor(*, wait: bool = True) -> None:
    _blocking_pool.shutdown(wait=wait)


# ストリーム反復用エグゼキュータをシャットダウンする
# Shut down the stream-iteration executor.
def shutdown_stream_executor(*, wait: bool = True) -> None:
    _stream_pool.shutdown(wait=wait)


# ブロッキングを伴う同期関数を非同期に実行するヘルパー関数
# Helper function to asynchronously run a blocking synchronous function
async def run_blocking(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    # 同期I/O関数を専用スレッドプールへ逃がし、イベントループのブロックを防ぐ
    # Offload blocking sync call to the dedicated pool to keep the event loop responsive.
    # kwargs 付き呼び出しも同じ経路で扱えるよう partial で束ねる
    # Bind positional/keyword args via partial for uniform thread execution.
    bound = partial(func, *args, **kwargs) if kwargs else partial(func, *args)
    loop = asyncio.get_running_loop()
    # 専用エグゼキュータ上で関数を実行し、完了を非同期に待機する
    # Execute the function on the dedicated executor and await completion asynchronously.
    return await loop.run_in_executor(get_blocking_executor(), bound)


# 同期イテレータの終端をスレッド境界越しに伝えるためのセンチネル。
# StopIteration は Future 経由では再送出できない（RuntimeError になる）ため、
# 終端は「例外」ではなく「値」として返す必要がある。
# Sentinel that carries a sync iterator's exhaustion across the thread boundary.
# StopIteration cannot travel through a Future, so exhaustion is returned as a value.
_ITERATION_DONE = object()


# 同期イテレータから1要素取り出し、終端はセンチネル値に置き換えて返す
# Pull one item from the sync iterator, returning the sentinel instead of raising StopIteration.
def _next_or_done(iterator: Iterator[T]) -> Any:
    try:
        return next(iterator)
    except StopIteration:
        return _ITERATION_DONE


# 同期イテレータの後始末を行う（close を持たないイテレータは無視する）
# Close the sync iterator if it exposes close(); plain iterators are ignored.
def _close_iterator(iterator: Any) -> None:
    close = getattr(iterator, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:
        # 日本語: 後始末の失敗で応答経路を壊さないため、記録だけ残します。
        # English: Never let cleanup failures break the response path; just record them.
        logger.debug("Failed to close an offloaded blocking iterator.", exc_info=True)


# 同期イテレータの取り出しを専用スレッドプールへ逃がし、非同期イテレータとして公開する
# Expose a blocking sync iterator as an async iterator backed by the stream thread pool.
async def iterate_blocking(iterable: Iterable[T]) -> AsyncIterator[T]:
    """
    ブロッキングする同期イテレータを、専用スレッドプール経由の非同期イテレータへ変換します。
    Starlette の `iterate_in_threadpool` を経由しないため、anyio 既定 CapacityLimiter
    （40トークン）を長時間占有しません。
    Converts a blocking sync iterator into an async iterator driven by the dedicated stream
    pool, so it never holds a token of anyio's default capacity limiter.
    """
    iterator = iter(iterable)
    loop = asyncio.get_running_loop()
    executor = get_stream_executor()
    pending: asyncio.Future[Any] | None = None
    try:
        while True:
            pending = loop.run_in_executor(executor, _next_or_done, iterator)
            # クライアント切断でこのジェネレータが閉じられても、走り出したワーカースレッドは
            # 中断できない。shield で「呼び出し側のキャンセル」と「スレッドの完了」を分離し、
            # 実行中のイテレータを外から close して ValueError になるのを防ぐ。
            # A disconnect cancels this generator but cannot interrupt a thread already inside
            # next(). Shielding separates caller cancellation from thread completion so the
            # iterator is never closed while it is still executing.
            item = await asyncio.shield(pending)
            if item is _ITERATION_DONE:
                pending = None
                return
            yield item
    finally:
        _schedule_iterator_close(iterator, pending, executor)


# ワーカースレッドが next() を抜けてから同期イテレータを閉じるよう予約する
# Arrange for the sync iterator to be closed once the worker thread leaves next().
def _schedule_iterator_close(
    iterator: Any,
    pending: asyncio.Future[Any] | None,
    executor: ThreadPoolExecutor,
) -> None:
    if pending is None or pending.done():
        # スレッドは既に next() を抜けている。イテレータは yield 地点で停止しているので
        # ここで閉じてよい（generator の finally が同期実行される）。
        # The thread already left next(); the iterator is parked on a yield and is safe to close.
        _close_iterator(iterator)
        return

    def _close_after_thread(future: asyncio.Future[Any]) -> None:
        # 「Future exception was never retrieved」の警告を避けるため結果を回収しておく。
        # Retrieve the outcome so asyncio does not log an unretrieved exception.
        if not future.cancelled():
            future.exception()
        try:
            executor.submit(_close_iterator, iterator)
        except RuntimeError:
            # 日本語: プロセス終了時などプール停止後は、GC による後始末に任せます。
            # English: After the pool is shut down (process exit) leave cleanup to the GC.
            logger.debug("Stream executor was already shut down during cleanup.", exc_info=True)

    pending.add_done_callback(_close_after_thread)


# プロセス終了時に自動でシャットダウンを実行するよう登録
# Register the shutdown handlers to be called automatically on process exit.
atexit.register(shutdown_blocking_executor)
atexit.register(shutdown_stream_executor)
