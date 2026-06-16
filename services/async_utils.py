from __future__ import annotations

import asyncio
import atexit
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# ブロッキングI/O（同期DB・外部HTTP・ファイル等）を逃がす専用スレッドプール。
# asyncio.to_thread の既定エグゼキュータ（プロセス共有・暗黙のサイズ）に依存せず、
# 1ワーカープロセスあたりの同時ブロッキング処理数を環境変数で明示制御する。
# Dedicated pool for blocking I/O (sync DB / outbound HTTP / files). Avoids relying on
# asyncio.to_thread's implicit shared default executor so the per-process concurrency
# budget for blocking work is explicit and tunable via the environment.
_DEFAULT_MAX_WORKERS = 64

_executor_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None


# 環境変数から正の整数を取得する（不正値・非正値は既定値へフォールバック）
# Read a positive int env var, falling back to the default on invalid/non-positive input.
def _get_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


# ブロッキング処理用スレッドプールの最大同時実行数を解決する
# Resolve the max concurrency for the blocking work thread pool.
def _resolve_max_workers() -> int:
    return _get_positive_int_env("RUN_BLOCKING_MAX_WORKERS", _DEFAULT_MAX_WORKERS)


# シングルトンのブロッキング用エグゼキュータを取得する（スレッドセーフな遅延初期化）
# Get the singleton blocking-work executor (thread-safe lazy initialization).
def get_blocking_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=_resolve_max_workers(),
                thread_name_prefix="chat-core-blocking",
            )
        return _executor


# ブロッキング用エグゼキュータをシャットダウンする
# Shut down the blocking-work executor.
def shutdown_blocking_executor(*, wait: bool = True) -> None:
    global _executor
    with _executor_lock:
        executor = _executor
        _executor = None
    if executor is not None:
        executor.shutdown(wait=wait)


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


# プロセス終了時に自動でシャットダウンを実行するよう登録
# Register the shutdown handler to be called automatically on process exit.
atexit.register(shutdown_blocking_executor)
