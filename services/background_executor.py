from __future__ import annotations

import atexit
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")

_executor_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None


def _get_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _create_executor() -> ThreadPoolExecutor:
    max_workers = _get_positive_int_env("BACKGROUND_WORKER_THREADS", 8)
    return ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="chat-core-bg",
    )


def get_background_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = _create_executor()
        return _executor


def submit_background_task(func: Any, *args: Any, **kwargs: Any) -> Future[T]:
    return get_background_executor().submit(func, *args, **kwargs)


def shutdown_background_executor(
    *,
    wait: bool = True,
    cancel_futures: bool = False,
) -> None:
    global _executor
    with _executor_lock:
        executor = _executor
        _executor = None

    if executor is None:
        return

    executor.shutdown(wait=wait, cancel_futures=cancel_futures)


atexit.register(shutdown_background_executor)
