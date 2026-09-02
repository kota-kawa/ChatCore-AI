import json
import threading
import time
import unittest
from unittest.mock import patch

from services.chat_generation import (
    REMOTE_CANCEL_CHECK_INTERVAL_SECONDS,
    ChatGenerationService,
)
from services.chat_turn_state import strip_turn_state_update
from services.web_search import WebSearchResult, WebSearchSource


# 日本語: 複数ワーカーが共有するRedisを模した、Pub/Sub付きの疑似Redisクライアント。
# English: Fake Redis client with Pub/Sub, emulating the store shared by multiple workers.
class _SharedFakeRedis:
    # 日本語: 値・リスト・購読キューの保持領域を初期化します。
    # English: Initialize storage for values, lists, and subscriber queues.
    def __init__(self):
        self._values = {}
        self._lists = {}
        self._subscribers = {}
        self._lock = threading.Lock()

    # 日本語: 指定キーに値を設定します。nx=Trueの場合は未登録のときだけ設定します。
    # English: Set a value for the key, only when absent if nx=True.
    def set(self, key, value, nx=False, ex=None):
        del ex
        with self._lock:
            if nx and key in self._values:
                return False
            self._values[key] = value
            return True

    # 日本語: 指定キーが存在するかどうかを返します。
    # English: Return whether the specified key exists.
    def exists(self, key):
        with self._lock:
            if key in self._values:
                return 1
            return 1 if self._lists.get(key) else 0

    # 日本語: 指定キーを削除します。
    # English: Delete the specified key.
    def delete(self, key):
        with self._lock:
            existed = key in self._values
            self._values.pop(key, None)
            return 1 if existed else 0

    # 日本語: リストキーの指定範囲の要素を取得します。
    # English: Retrieve elements in the given range from a list key.
    def lrange(self, key, start, end):
        with self._lock:
            values = list(self._lists.get(key, []))
        if not values:
            return []
        if end < 0:
            end = len(values) - 1
        return values[start : end + 1]

    # 日本語: リストキーの末尾に値を追加します。
    # English: Append a value to the tail of a list key.
    def rpush(self, key, value):
        with self._lock:
            self._lists.setdefault(key, []).append(value)
            return len(self._lists[key])

    # 日本語: 有効期限の設定を模擬します（テストでは常に成功扱い）。
    # English: Simulate setting an expiration (always succeeds in tests).
    def expire(self, key, ttl):
        del key, ttl
        return True

    # 日本語: 購読中のすべてのキューへメッセージを配信します。
    # English: Deliver the message to every subscribed queue.
    def publish(self, channel, message):
        with self._lock:
            queues = list(self._subscribers.get(channel, []))
        for queue in queues:
            queue.append(message)
        return len(queues)

    # 日本語: 疑似Pub/Subインスタンスを返します。
    # English: Return a fake Pub/Sub instance.
    def pubsub(self, ignore_subscribe_messages=True):
        del ignore_subscribe_messages
        return _FakePubSub(self)

    # 日本語: 指定チャンネルの購読キューを登録します。
    # English: Register a subscriber queue for the given channel.
    def register_subscriber(self, channel, queue):
        with self._lock:
            self._subscribers.setdefault(channel, []).append(queue)

    # 日本語: 購読キューの登録を解除します。
    # English: Deregister a subscriber queue.
    def unregister_subscriber(self, channel, queue):
        with self._lock:
            queues = self._subscribers.get(channel, [])
            if queue in queues:
                queues.remove(queue)

    # 日本語: パイプラインを模擬し、コマンドを順に実行します。
    # English: Emulate a pipeline by executing queued commands in order.
    def pipeline(self):
        return _FakePipeline(self)

    # 日本語: ロック解放用Luaスクリプトを模擬し、トークン一致時のみ削除します。
    # English: Emulate the lock-release Lua script, deleting only on a token match.
    def eval(self, script, key_count, key, token):
        del script, key_count
        with self._lock:
            if self._values.get(key) == token:
                del self._values[key]
                return 1
            return 0


# 日本語: 購読キューをポーリングする疑似Pub/Subクラス。
# English: Fake Pub/Sub class polling a subscriber queue.
class _FakePubSub:
    # 日本語: 購読状態を初期化します。
    # English: Initialize the subscription state.
    def __init__(self, redis_client):
        self._redis = redis_client
        self._queue = []
        self._channel = None

    # 日本語: 指定チャンネルを購読します。
    # English: Subscribe to the specified channel.
    def subscribe(self, channel):
        self._channel = channel
        self._redis.register_subscriber(channel, self._queue)

    # 日本語: メッセージが届くまで指定秒数まで待ってから返します。
    # English: Wait up to the timeout for a message, then return it.
    def get_message(self, timeout=0.0):
        deadline = time.monotonic() + timeout
        while True:
            if self._queue:
                return {"type": "message", "data": self._queue.pop(0)}
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.005)

    # 日本語: 購読を解除して閉じます。
    # English: Unsubscribe and close.
    def close(self):
        if self._channel is not None:
            self._redis.unregister_subscriber(self._channel, self._queue)
            self._channel = None


# 日本語: rpush/expire/publish をまとめて実行する疑似パイプライン。
# English: Fake pipeline batching rpush/expire/publish calls.
class _FakePipeline:
    # 日本語: コマンドバッファを初期化します。
    # English: Initialize the command buffer.
    def __init__(self, redis_client):
        self._redis = redis_client
        self._commands = []

    # 日本語: rpush コマンドをバッファへ積みます。
    # English: Queue an rpush command.
    def rpush(self, key, value):
        self._commands.append(("rpush", key, value))
        return self

    # 日本語: expire コマンドをバッファへ積みます。
    # English: Queue an expire command.
    def expire(self, key, ttl):
        self._commands.append(("expire", key, ttl))
        return self

    # 日本語: publish コマンドをバッファへ積みます。
    # English: Queue a publish command.
    def publish(self, channel, message):
        self._commands.append(("publish", channel, message))
        return self

    # 日本語: 積んだコマンドをまとめて実行します。
    # English: Execute all queued commands.
    def execute(self):
        for command, key, value in self._commands:
            getattr(self._redis, command)(key, value)
        self._commands.clear()
        return True


# 日本語: 回答可能と判断した後、キャンセルまで本文を送り続けるモデルを模擬します。
# English: Emulate a model that decides it can answer, then emits body chunks until cancelled.
def _endless_answer_stream(messages, model, tools=None, generation_phase="default"):
    del messages, model, tools, generation_phase
    yield (
        '<turn_state_update>{"objective":"こんにちは",'
        '"unresolved_questions":[],"facts":[],"evidence_ids":[],'
        '"ready_to_answer":true}</turn_state_update>'
    )
    for index in range(2000):
        time.sleep(0.01)
        yield f"chunk-{index} "


def _web_search_tool_call(query):
    return json.dumps(
        [
            {
                "id": "call-web-search",
                "type": "function",
                "function": {
                    "name": "web_search",
                    "arguments": json.dumps({"query": query}, ensure_ascii=False),
                },
            }
        ],
        ensure_ascii=False,
    )


# 日本語: 生成中に条件が満たされるまで待機するヘルパー。
# English: Helper waiting until the given condition holds.
def _wait_until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


# 日本語: 複数ワーカー構成における生成停止（赤い停止ボタン）の挙動を検証するテストクラス。
# English: Test class covering generation stop (the red stop button) across multiple workers.
class ChatGenerationStopTestCase(unittest.TestCase):
    # 日本語: 共有Redisと2ワーカー分のサービスを用意します。
    # English: Prepare the shared Redis and one service per simulated worker.
    def setUp(self):
        self.redis = _SharedFakeRedis()
        self.owner = self._build_service()
        self.other_worker = self._build_service()
        self.job_key = "user:1:room-1"

    # 日本語: 実行中ジョブを片付けます。
    # English: Tear down any job left running.
    def tearDown(self):
        self.owner.reset_in_memory_state(cancel_running=True)
        self.other_worker.reset_in_memory_state(cancel_running=True)

    # 日本語: 共有Redisを参照する生成サービスを構築します。
    # English: Build a generation service backed by the shared Redis.
    def _build_service(self, **kwargs):
        return ChatGenerationService(
            redis_client_getter=lambda: self.redis,
            **kwargs,
        )

    # 日本語: 生成ジョブを開始し、最初の本文チャンクが出力または保留されるまで待ちます。
    # English: Start a generation job and wait until the first body chunk is emitted or buffered.
    def _start_job(self, service, persisted=None):
        job = service.start_generation_job(
            self.job_key,
            conversation_messages=[{"role": "user", "content": "こんにちは"}],
            model="openai/gpt-oss-120b",
            persist_response=(
                (lambda response, **kwargs: persisted.append(response))
                if persisted is not None
                else (lambda response, **kwargs: None)
            ),
        )
        # 内部状態の封筒だけが届いた時点では本文がまだ無い。停止のテストは、表示される
        # 本文が生成され始めてから停止させる必要がある。
        # Only the internal envelope has arrived at first, and there is no body yet. A stop
        # test must wait until user-facing text has actually started.
        self.assertTrue(
            _wait_until(
                lambda: bool(job._chunks)
                or bool(strip_turn_state_update("".join(job._pending_stream_chunks)))
            )
        )
        return job

    # 日本語: 回答出力中のジョブへ別ワーカーから停止要求しても、部分回答を保存しロックを解放することを検証します。
    # English: Verify a remote stop during answer output persists the partial answer and frees the lock.
    def test_stop_during_answer_output_persists_partial_response(self):
        persisted = []
        with patch(
            "services.chat_generation.get_llm_response_stream",
            side_effect=_endless_answer_stream,
        ):
            job = self._start_job(self.owner, persisted)

            cancelled = self.other_worker.cancel_generation_job(self.job_key)

        self.assertTrue(cancelled)
        self.assertTrue(job.is_done)
        self.assertFalse(self.owner.has_active_generation(self.job_key))
        # 停止を受けたワーカー側からも、ルームが生成中でないと見えること。
        # The worker that handled the stop must also see the room as idle.
        self.assertFalse(self.other_worker.has_active_generation(self.job_key))
        # 停止までに生成できた本文は失われず保存されること。
        # Text produced before the stop is persisted rather than dropped.
        self.assertTrue(persisted)
        self.assertNotIn("turn_state_update", persisted[0])

    # 日本語: モデルがTurnStateを更新している途中に停止した場合、内部状態を回答として保存しないことを検証します。
    # English: Verify stopping while the model updates TurnState never persists internal state as an answer.
    def test_stop_during_model_decision_does_not_persist_turn_state(self):
        persisted = []
        decision_started = threading.Event()

        def deciding_stream(messages, model, tools=None, generation_phase="default"):
            del messages, model, tools, generation_phase
            decision_started.set()
            yield '<turn_state_update>{"objective":"こんにちは",'
            for _ in range(2000):
                time.sleep(0.01)
                yield '"unresolved_questions":['

        with patch(
            "services.chat_generation.get_llm_response_stream",
            side_effect=deciding_stream,
        ):
            job = self.owner.start_generation_job(
                self.job_key,
                conversation_messages=[{"role": "user", "content": "こんにちは"}],
                model="openai/gpt-oss-120b",
                persist_response=lambda response, **kwargs: persisted.append(response),
            )
            self.assertTrue(decision_started.wait(timeout=5.0))
            self.assertTrue(self.other_worker.cancel_generation_job(self.job_key))

        self.assertTrue(job.is_done)
        self.assertEqual(persisted, [])
        self.assertFalse(self.owner.has_active_generation(self.job_key))

    # 日本語: ツール実行後の停止で次のモデル判断が中断され、検索結果を回答として保存しないことを検証します。
    # English: Verify a stop after tool execution interrupts the next decision without persisting evidence as an answer.
    def test_stop_after_tool_execution_does_not_persist_tool_result(self):
        persisted = []
        search_completed = threading.Event()
        stream_call_count = 0
        search_result = WebSearchResult(
            query="東京の天気",
            searched_at="2026-09-02T00:00:00+00:00",
            sources=(
                WebSearchSource(
                    url="https://example.com/weather",
                    title="東京の天気",
                    hostname="example.com",
                    age="",
                    snippets=("晴れです。",),
                ),
            ),
        )

        def stream_side_effect(messages, model, tools=None, generation_phase="default"):
            nonlocal stream_call_count
            del messages, model, generation_phase
            stream_call_count += 1
            if stream_call_count == 1:
                self.assertIsNotNone(tools)
                yield (
                    '<turn_state_update>{"objective":"東京の天気",'
                    '"unresolved_questions":["最新の天気"],"facts":[],'
                    '"evidence_ids":[],"ready_to_answer":false}</turn_state_update>'
                )
                yield _web_search_tool_call("東京の天気")
                return

            search_completed.set()
            for _ in range(2000):
                time.sleep(0.01)
                yield '<turn_state_update>{"objective":"東京の天気"'

        with (
            patch(
                "services.chat_generation.get_llm_response_stream",
                side_effect=stream_side_effect,
            ),
            patch(
                "services.chat_generation.search_brave_llm_context",
                return_value=search_result,
            ) as mock_search,
            patch("services.chat_generation.choose_web_search_images", return_value=[]),
        ):
            job = self.owner.start_generation_job(
                self.job_key,
                conversation_messages=[
                    {"role": "user", "content": "東京の天気を教えて"}
                ],
                model="openai/gpt-oss-120b",
                persist_response=lambda response, **kwargs: persisted.append(response),
            )
            self.assertTrue(search_completed.wait(timeout=5.0))
            self.assertTrue(self.other_worker.cancel_generation_job(self.job_key))

        self.assertTrue(job.is_done)
        self.assertEqual(mock_search.call_count, 1)
        self.assertEqual(persisted, [])
        self.assertFalse(self.owner.has_active_generation(self.job_key))

    # 日本語: 停止直後に同じルームで再生成を開始できることを検証します。
    # English: Verify regeneration can start for the same room right after a stop.
    def test_regeneration_is_allowed_immediately_after_remote_stop(self):
        with patch(
            "services.chat_generation.get_llm_response_stream",
            side_effect=_endless_answer_stream,
        ):
            self._start_job(self.owner)
            self.other_worker.cancel_generation_job(self.job_key)

            regenerated = self._start_job(self.other_worker)
            self.assertFalse(regenerated.is_done)
            regenerated.cancel()

    # 日本語: 所有ワーカーが応答しない場合でも、待機上限を過ぎたらロックを解放して再生成を許すことを検証します。
    # English: Verify an unresponsive owner does not wedge the room: the lock is freed after the timeout.
    def test_stop_releases_lock_when_owning_worker_never_responds(self):
        stopper = self._build_service(remote_cancel_timeout_seconds=0.2)
        lock_key = stopper._active_lock_key(self.job_key)
        # 応答しないワーカーが握ったままのロックを再現する。
        # Reproduce a lock still held by a worker that never answers.
        self.redis.set(lock_key, "orphaned-token")

        cancelled = stopper.cancel_generation_job(self.job_key)

        self.assertTrue(cancelled)
        self.assertFalse(stopper.has_active_generation(self.job_key))

    # 日本語: Pub/Sub通知を取りこぼしても、停止要求マーカーの定期確認でジョブが停止することを検証します。
    # English: Verify the periodic marker check stops the job even when the pub/sub notice is missed.
    def test_running_job_stops_itself_from_the_cancel_request_marker(self):
        with patch(
            "services.chat_generation.get_llm_response_stream",
            side_effect=_endless_answer_stream,
        ):
            job = self._start_job(self.owner)
            self.redis.set(self.owner._cancel_request_key(self.job_key), "1")

            self.assertTrue(
                _wait_until(
                    lambda: job.is_done,
                    timeout=REMOTE_CANCEL_CHECK_INTERVAL_SECONDS + 5.0,
                )
            )

        self.assertFalse(self.owner.has_active_generation(self.job_key))

    # 日本語: 前回の停止要求マーカーが残っていても、新しい生成ジョブが巻き添えで止まらないことを検証します。
    # English: Verify a leftover stop-request marker does not abort the next generation job.
    def test_new_job_clears_a_stale_cancel_request_marker(self):
        cancel_key = self.owner._cancel_request_key(self.job_key)
        self.redis.set(cancel_key, "1")

        with patch(
            "services.chat_generation.get_llm_response_stream",
            side_effect=_endless_answer_stream,
        ):
            job = self._start_job(self.owner)
            self.assertFalse(self.redis.exists(cancel_key))
            time.sleep(REMOTE_CANCEL_CHECK_INTERVAL_SECONDS + 0.2)
            self.assertFalse(job.is_done)
            job.cancel()


if __name__ == "__main__":
    unittest.main()
