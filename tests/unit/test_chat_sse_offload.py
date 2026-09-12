"""SSE ストリームが Starlette の共有スレッドプールを使わないことを検証するテスト。

Tests that SSE streaming never runs on Starlette's shared anyio threadpool.
"""

import asyncio
import threading
import unittest
from collections.abc import AsyncIterator, Iterator
from unittest.mock import patch

from blueprints.chat.messages import _build_llm_stream_response
from services.async_utils import iterate_blocking


# 日本語: 非同期イテレータをすべて読み切ってリストへ集めます。
# English: Drain an async iterator into a list.
async def _drain(source: AsyncIterator[bytes]) -> list[bytes]:
    return [item async for item in source]


# 日本語: SSE レスポンスがブロッキング反復を専用プールへ逃がすことを検証するテストクラス。
# English: Test class covering the SSE response offloading blocking iteration to its own pool.
class ChatSseOffloadTestCase(unittest.TestCase):
    # 日本語: SSE レスポンスの本体が非同期イテレータであることを検証します。
    # English: Verify the SSE response body is an async iterator.
    def test_llm_stream_response_body_is_an_async_iterator(self):
        response = _build_llm_stream_response(iter([b"event: done\n\n"]))

        self.assertTrue(hasattr(response.body_iterator, "__anext__"))
        self.assertFalse(hasattr(response.body_iterator, "__next__"))
        self.assertEqual(response.media_type, "text/event-stream")
        asyncio.run(response.body_iterator.aclose())

    # 日本語: Starlette の共有スレッドプール（anyio の 40 トークン）を経由しないことを検証します。
    # English: Verify the stream never goes through Starlette's shared anyio threadpool.
    def test_llm_stream_response_does_not_use_starlette_threadpool(self):
        with patch("starlette.responses.iterate_in_threadpool") as iterate_in_threadpool:
            response = _build_llm_stream_response(iter([b"event: done\n\n"]))

        iterate_in_threadpool.assert_not_called()
        asyncio.run(response.body_iterator.aclose())

    # 日本語: 反復が SSE 専用スレッドプール上で実行されることを検証します。
    # English: Verify iteration runs on the dedicated SSE thread pool.
    def test_iteration_runs_on_the_dedicated_stream_pool(self):
        thread_names: list[str] = []

        def _events() -> Iterator[bytes]:
            for index in range(3):
                thread_names.append(threading.current_thread().name)
                yield f"data: {index}\n\n".encode()

        payload = asyncio.run(_drain(iterate_blocking(_events())))

        self.assertEqual(payload, [b"data: 0\n\n", b"data: 1\n\n", b"data: 2\n\n"])
        self.assertEqual(len(thread_names), 3)
        for name in thread_names:
            self.assertTrue(name.startswith("chat-core-stream"), name)
            self.assertNotEqual(name, threading.current_thread().name)

    # 日本語: StopIteration がスレッド境界を越えても、ストリームが正常終了することを検証します。
    # English: Verify exhaustion terminates the stream even though StopIteration cannot cross threads.
    def test_exhausted_sync_iterator_ends_the_stream_without_error(self):
        response = _build_llm_stream_response(iter([b"id: 1\nevent: done\n\n"]))

        payload = asyncio.run(_drain(response.body_iterator))

        self.assertEqual(payload, [b"id: 1\nevent: done\n\n"])

    # 日本語: クライアント切断（ジェネレータの close）で同期イテレータが閉じられることを検証します。
    # English: Verify a client disconnect closes the underlying sync iterator.
    def test_disconnect_closes_the_sync_iterator(self):
        closed = threading.Event()

        def _events() -> Iterator[bytes]:
            try:
                yield b"data: 1\n\n"
                yield b"data: 2\n\n"
            finally:
                closed.set()

        async def _scenario() -> None:
            stream = iterate_blocking(_events())
            self.assertEqual(await stream.__anext__(), b"data: 1\n\n")
            await stream.aclose()

        asyncio.run(_scenario())

        self.assertTrue(closed.is_set())

    # 日本語: ブロッキング中に切断されても、スレッド完了後に後片付けされることを検証します。
    # English: Verify cleanup still happens after the worker thread leaves a blocking next().
    def test_disconnect_during_a_blocking_next_cleans_up_after_the_thread(self):
        closed = threading.Event()
        entered_block = threading.Event()
        release_block = threading.Event()

        def _events() -> Iterator[bytes]:
            try:
                yield b"data: 1\n\n"
                entered_block.set()
                release_block.wait(10)
                yield b"data: 2\n\n"
            finally:
                closed.set()

        async def _scenario() -> None:
            stream = iterate_blocking(_events())
            self.assertEqual(await stream.__anext__(), b"data: 1\n\n")

            pending = asyncio.ensure_future(stream.__anext__())
            await asyncio.to_thread(entered_block.wait, 10)

            # クライアント切断に相当するキャンセル。ワーカースレッドはまだ next() の中にいる。
            # Cancellation stands in for the disconnect while the worker is still inside next().
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending

            # 走っているイテレータを外から閉じてはいけないので、まだ閉じていないこと。
            # The still-executing iterator must not have been closed from the outside yet.
            self.assertFalse(closed.is_set())

            release_block.set()
            # 後片付けはワーカースレッドが next() を抜けたあとに予約されるため、
            # イベントループを動かしたまま完了を待つ。
            # Cleanup is scheduled once the worker leaves next(), so keep the loop running.
            await asyncio.to_thread(closed.wait, 10)

        asyncio.run(_scenario())

        self.assertTrue(closed.is_set())


if __name__ == "__main__":
    unittest.main()
