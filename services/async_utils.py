from __future__ import annotations

import asyncio
import threading
from functools import partial
from typing import Any, Callable, TypeVar

T = TypeVar("T")


async def run_blocking(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    # 同期I/O関数をスレッドプールへ逃がし、イベントループのブロックを防ぐ
    # Offload blocking sync call to threadpool to keep the event loop responsive.
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[T] = loop.create_future()
    bound = partial(func, *args, **kwargs) if kwargs else partial(func, *args)

    def runner() -> None:
        try:
            result = bound()
        except BaseException as exc:
            loop.call_soon_threadsafe(result_future.set_exception, exc)
        else:
            loop.call_soon_threadsafe(result_future.set_result, result)

    threading.Thread(target=runner, daemon=True).start()
    return await result_future
