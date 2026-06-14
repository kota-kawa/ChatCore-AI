from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, Callable, TypeVar

T = TypeVar("T")


# 日本語: run blocking の実行処理を非同期で担当します。
# English: Handle running for run blocking asynchronously.
async def run_blocking(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    # 同期I/O関数をスレッドプールへ逃がし、イベントループのブロックを防ぐ
    # Offload blocking sync call to threadpool to keep the event loop responsive.
    # kwargs 付き呼び出しも同じ経路で扱えるよう partial で束ねる
    # Bind positional/keyword args via partial for uniform thread execution.
    bound = partial(func, *args, **kwargs) if kwargs else partial(func, *args)
    return await asyncio.to_thread(bound)
