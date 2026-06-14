from __future__ import annotations

import atexit
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")

_executor_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None


# 環境変数から正の整数値を取得するヘルパー関数
# Helper function to get a positive integer from environment variables
def _get_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


# バックグラウンドタスク実行用のスレッドプールエグゼキュータを生成する
# Create a thread pool executor for running background tasks
def _create_executor() -> ThreadPoolExecutor:
    max_workers = _get_positive_int_env("BACKGROUND_WORKER_THREADS", 8)
    return ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="chat-core-bg",
    )


# シングルトンのバックグラウンドタスク用エグゼキュータを取得する（スレッドセーフ）
# Get the singleton thread pool executor for background tasks (thread-safe)
def get_background_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = _create_executor()
        return _executor


# 関数をバックグラウンドタスクとしてスレッドプールに投入する
# Submit a function to be executed as a background task in the thread pool
def submit_background_task(func: Any, *args: Any, **kwargs: Any) -> Future[T]:
    return get_background_executor().submit(func, *args, **kwargs)


# バックグラウンドタスク用のエグゼキュータをシャットダウンする
# Shutdown the thread pool executor for background tasks
def shutdown_background_executor(
    *,
    wait: bool = True,
    cancel_futures: bool = False,
) -> None:
    global _executor
    # ロック内でエグゼキュータへの参照を取り出し、グローバル変数をクリア
    # Retrieve the executor reference and clear the global variable within the lock
    with _executor_lock:
        executor = _executor
        _executor = None

    if executor is None:
        return

    executor.shutdown(wait=wait, cancel_futures=cancel_futures)


# プロセス終了時に自動でシャットダウンを実行するよう登録
# Register the shutdown handler to be called automatically on process exit
atexit.register(shutdown_background_executor)
