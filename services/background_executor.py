from __future__ import annotations

import atexit
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")

_executor_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None


# 日本語: get positive int env の取得処理を担当します。
# English: Handle fetching for get positive int env.
def _get_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if raw is None:
        return default
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


# 日本語: create executor の作成処理を担当します。
# English: Handle creating for create executor.
def _create_executor() -> ThreadPoolExecutor:
    max_workers = _get_positive_int_env("BACKGROUND_WORKER_THREADS", 8)
    return ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="chat-core-bg",
    )


# 日本語: get background executor の取得処理を担当します。
# English: Handle fetching for get background executor.
def get_background_executor() -> ThreadPoolExecutor:
    global _executor
    # 日本語: 必要なリソースやコンテキストを限定して利用します。
    # English: Use the required resource or context within this limited block.
    with _executor_lock:
        if _executor is None:
            _executor = _create_executor()
        return _executor


# 日本語: submit background task に関する処理の入口です。
# English: Entry point for logic related to submit background task.
def submit_background_task(func: Any, *args: Any, **kwargs: Any) -> Future[T]:
    return get_background_executor().submit(func, *args, **kwargs)


# 日本語: shutdown background executor に関する処理の入口です。
# English: Entry point for logic related to shutdown background executor.
def shutdown_background_executor(
    *,
    wait: bool = True,
    cancel_futures: bool = False,
) -> None:
    global _executor
    # 日本語: 必要なリソースやコンテキストを限定して利用します。
    # English: Use the required resource or context within this limited block.
    with _executor_lock:
        executor = _executor
        _executor = None

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if executor is None:
        return

    executor.shutdown(wait=wait, cancel_futures=cancel_futures)


atexit.register(shutdown_background_executor)
