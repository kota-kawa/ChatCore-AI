"""
生成ワーカースレッドから非同期コールバックを実行するための橋渡しヘルパーです。
Bridge helper that runs async callbacks from the synchronous generation worker thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

# 日本語: 名前は `_run_async_callback` に固定しています。バックグラウンドへ渡した関数の
#         `__name__` を検証しているテストがあるため、リネームすると失敗します。
# English: The name `_run_async_callback` is pinned: a test asserts the `__name__` of the
#          callable handed to the background executor, so renaming it would break that check.


def _run_async_callback(coroutine_factory: Callable[[], Awaitable[Any]]) -> Any:
    """
    生成ワーカースレッドから非同期のDBコールバックを実行します。
    Run an async DB callback from the generation worker thread.
    """
    return asyncio.run(coroutine_factory())
