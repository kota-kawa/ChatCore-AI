"""チャット生成のプロセス間協調（Redis Pub/Sub・分散ロック・停止要求）を担うモジュール。

Owns the cross-process coordination for chat generation: Redis pub/sub, the distributed
active-job lock, remote stop requests, and reading events written by another worker.

ジョブのライフサイクル（生成の開始・保持・期限切れ）は `services/chat_generation.py`
の `ChatGenerationService` が持ち続ける。このモジュールは「別プロセスとどう話すか」
だけを担い、ローカルジョブの操作はコールバック経由で呼び出し元へ委ねる。
Job lifecycle (starting, holding and expiring generations) stays in
`ChatGenerationService`. This module only knows how to talk to the other workers and
reaches back into local jobs through the callbacks it is given.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from services.cache import get_redis_client

logger = logging.getLogger(__name__)

# 停止要求が別ワーカーへ届いた場合に、所有ワーカーの応答を待つ再確認間隔。
# How often the waiting worker re-checks the lock after a stop request lands on it.
REMOTE_CANCEL_POLL_INTERVAL_SECONDS = 0.05
# 停止要求マーカーの保持時間と、生成ジョブ側がそれを再確認する間隔。
# Lifetime of the stop-request marker and how often a running job re-checks it.
REMOTE_CANCEL_REQUEST_TTL_SECONDS = 60
REMOTE_CANCEL_CHECK_INTERVAL_SECONDS = 1.0
_ACTIVE_JOB_LOCK_KEY_PREFIX = "chat_generation:active"
_CANCEL_REQUEST_KEY_PREFIX = "chat_generation:cancel"
_CANCEL_CHANNEL_NAME = "chat_generation:cancel:channel"
_EVENT_STREAM_KEY_PREFIX = "chat_generation:events"
_EVENT_CHANNEL_KEY_PREFIX = "chat_generation:events:channel"
_TERMINAL_EVENTS = {"done", "error", "aborted", "incomplete"}


def decode_redis_text(raw: Any) -> str | None:
    """Return Redis payloads as text regardless of the client's decode settings."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8")
        except Exception:
            # 日本語: Redis から UTF-8 として解釈できない値が返った場合は無視します。
            # English: Ignore values coming back from Redis that cannot be decoded as UTF-8.
            logger.debug("Discarded a non-UTF-8 value read from Redis.", exc_info=True)
            return None
    return None


# チャット生成イベントの待機中にタイムアウトが発生したことを表す例外クラス
# Exception class representing a timeout during waiting for chat generation events
class ChatGenerationStreamTimeoutError(RuntimeError):
    # 例外を初期化する
    # Initialize the exception
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.payload = {
            "message": message,
            "retryable": True,
        }


# チャット応答生成中に発生する各種イベントを表すデータクラス
# Dataclass representing various events occurring during chat response generation
@dataclass(frozen=True)
class ChatGenerationEvent:
    sequence_id: int
    event: str
    payload: dict[str, Any]


# 生成ジョブのプロセス間協調だけを担うコラボレータ。
# ジョブそのものは持たず、ローカルジョブへの操作はコールバックで呼び戻す。
# The collaborator that owns cross-process coordination only. It holds no jobs and reaches
# local jobs through the callbacks supplied by the service.
class ChatGenerationCoordinator:
    # 協調オブジェクトを初期化する
    # Initialize the coordinator
    def __init__(
        self,
        *,
        job_retention_seconds: int,
        active_job_lock_ttl_seconds: int,
        distributed_stream_idle_timeout_seconds: float,
        sse_heartbeat_seconds: float,
        remote_cancel_timeout_seconds: float,
        cancel_local_job: Callable[[str], bool],
        has_running_local_jobs: Callable[[], bool],
        redis_client_getter: Callable[[], Any | None] | None = None,
    ) -> None:
        self._job_retention_seconds = job_retention_seconds
        self._active_job_lock_ttl_seconds = active_job_lock_ttl_seconds
        self._distributed_stream_idle_timeout_seconds = distributed_stream_idle_timeout_seconds
        self._sse_heartbeat_seconds = sse_heartbeat_seconds
        self._remote_cancel_timeout_seconds = remote_cancel_timeout_seconds
        self._cancel_local_job = cancel_local_job
        self._has_running_local_jobs = has_running_local_jobs
        self._redis_client_getter = redis_client_getter
        self._cancel_listener_thread: threading.Thread | None = None
        self._cancel_listener_lock = threading.Lock()

    # Redis クライアントを取得する
    # Retrieve the Redis client
    def get_redis_client(self) -> Any | None:
        if self._redis_client_getter is not None:
            return self._redis_client_getter()
        return get_redis_client()

    # Redis が有効で分散ストリーミングに対応しているかを確認する
    # Check if Redis is enabled and supports distributed streaming
    def supports_distributed_streaming(self) -> bool:
        return self.get_redis_client() is not None

    # アクティブジョブの Redis ロックキーを生成する
    # Generate the Redis lock key for the active job
    def active_lock_key(self, job_key: str) -> str:
        return f"{_ACTIVE_JOB_LOCK_KEY_PREFIX}:{job_key}"

    # 停止要求マーカーの Redis キーを生成する
    # Generate the Redis key for the stop-request marker
    def cancel_request_key(self, job_key: str) -> str:
        return f"{_CANCEL_REQUEST_KEY_PREFIX}:{job_key}"

    # Redis に保存するイベントストリームのキーを生成する
    # Generate the Redis event stream key
    def event_stream_key(self, job_key: str) -> str:
        return f"{_EVENT_STREAM_KEY_PREFIX}:{job_key}"

    # Redis Pub/Sub のイベントチャネル名を生成する
    # Generate the Redis Pub/Sub event channel name
    def event_channel_name(self, job_key: str) -> str:
        return f"{_EVENT_CHANNEL_KEY_PREFIX}:{job_key}"

    # イベントオブジェクトを JSON 文字列にシリアライズする
    # Serialize the event object to a JSON string
    def serialize_event(self, event: ChatGenerationEvent) -> str:
        # Redis には SSE と同じ最小構造だけを保存する。payload の中身はイベント種別ごとに変わる。
        return json.dumps(
            {
                "id": event.sequence_id,
                "event": event.event,
                "payload": event.payload,
            },
            ensure_ascii=False,
        )

    # JSON 文字列をイベントオブジェクトにデシリアライズする
    # Deserialize a JSON string to an event object
    def deserialize_event(self, raw: str) -> ChatGenerationEvent | None:
        # Redis 上の古い/壊れた値はストリーム全体を落とさず読み飛ばす。
        try:
            loaded = json.loads(raw)
        except Exception:
            # 日本語: 壊れたイベント値はストリーム全体を落とさず読み飛ばしますが、記録は残します。
            # English: A corrupted event value is skipped rather than failing the stream, but it is still recorded.
            logger.debug("Skipped a corrupted chat generation event stored in Redis.", exc_info=True)
            return None
        if not isinstance(loaded, dict):
            return None
        sequence_id = loaded.get("id")
        event_name = loaded.get("event")
        payload = loaded.get("payload")
        if not isinstance(sequence_id, int) or sequence_id <= 0:
            return None
        if not isinstance(event_name, str) or not event_name:
            return None
        if not isinstance(payload, dict):
            payload = {}
        return ChatGenerationEvent(
            sequence_id=sequence_id,
            event=event_name,
            payload=payload,
        )

    # Redis 経由で分散イベントを配信する（リストへの追記および Pub/Sub 発行）
    # Publish a distributed event via Redis (append to list and publish via Pub/Sub)
    def publish_event(self, job_key: str, event: ChatGenerationEvent) -> None:
        redis_client = self.get_redis_client()
        if redis_client is None:
            return
        serialized = self.serialize_event(event)
        stream_key = self.event_stream_key(job_key)
        channel = self.event_channel_name(job_key)
        ttl_seconds = max(
            self._job_retention_seconds + self._active_job_lock_ttl_seconds,
            self._job_retention_seconds,
            1,
        )
        # list は再接続時のリプレイ用、pub/sub は今つながっている SSE への即時通知用。
        # どちらか片方だけでは「取りこぼしなし」と「低遅延」を同時に満たせない。
        try:
            pipeline = redis_client.pipeline()
            pipeline.rpush(stream_key, serialized)
            pipeline.expire(stream_key, ttl_seconds)
            pipeline.publish(channel, serialized)
            pipeline.execute()
        except Exception:
            logger.exception("Failed to publish chat generation event to Redis.")

    # Redis のイベントストリームから指定されたシーケンスIDより後のイベントを読み出す
    # Read events from the Redis event stream after the specified sequence ID
    def read_events(
        self,
        job_key: str,
        *,
        after_sequence_id: int = 0,
    ) -> list[ChatGenerationEvent]:
        redis_client = self.get_redis_client()
        if redis_client is None:
            return []
        try:
            raw_items = redis_client.lrange(self.event_stream_key(job_key), 0, -1)
        except Exception:
            logger.exception("Failed to read Redis chat generation event stream.")
            return []

        events: list[ChatGenerationEvent] = []
        for item in raw_items:
            # Redis クライアント設定により bytes/str が混在しうる。ここでは str だけを扱い、
            # pub/sub 側の bytes デコードとは分けておく。
            if not isinstance(item, str):
                continue
            event = self.deserialize_event(item)
            if event is None:
                continue
            if event.sequence_id <= after_sequence_id:
                continue
            events.append(event)
        return events

    # 再生できるイベント履歴が Redis 上に残っているかを確認する
    # Check whether replayable event history still exists in Redis
    def has_replay_history(self, job_key: str) -> bool:
        redis_client = self.get_redis_client()
        if redis_client is None:
            return False
        try:
            return bool(redis_client.exists(self.event_stream_key(job_key)))
        except Exception:
            logger.exception("Redis chat generation replay-state check failed.")
            return False

    # 指定したジョブキーに対して Redis アクティブジョブロックの取得を試みる
    # Redis が応答しない場合はフェイルクローズ（未取得扱い）する。
    # Attempt to acquire the Redis active job lock for the specified job key.
    # Fails closed (reported as not acquired) when Redis does not answer.
    def try_acquire_active_job_lock(self, job_key: str) -> tuple[bool, str | None]:
        redis_client = self.get_redis_client()
        if redis_client is None:
            return True, None

        lock_key = self.active_lock_key(job_key)
        lock_token = uuid.uuid4().hex
        # NX + TTL でプロセス間の二重生成を防ぐ。TTL はプロセス異常終了時にロックが残り続けないための保険。
        try:
            acquired = redis_client.set(
                lock_key,
                lock_token,
                nx=True,
                ex=self._active_job_lock_ttl_seconds,
            )
        except Exception:
            # ロック状態を確認できない以上、取得できたものとして扱ってはいけない。
            # フェイルオープンすると Redis 障害中に複数ワーカーが同じターンを生成し、
            # 回答の二重保存と LLM の二重課金が起きる。取得失敗として扱い、呼び出し側の
            # 409（生成中）経路へ倒す。Redis 未設定・接続不可（クライアントが None）の
            # 単一プロセス構成は上の分岐で従来どおり通す。
            # A lock whose state cannot be read must not be treated as held. Failing open lets
            # several workers generate the same turn during a Redis outage, double-saving the
            # answer and double-billing the LLM, so this fails closed instead. Deployments with
            # no reachable Redis at all still pass through the `is None` branch above.
            logger.exception(
                "Redis chat generation lock acquisition failed; refusing to start the job."
            )
            return False, None

        if acquired:
            return True, lock_token
        return False, None

    # 自分が取得した Redis アクティブジョブロックを解放する
    # Release the Redis active job lock that was acquired by this instance
    def release_active_job_lock(self, job_key: str, lock_token: str | None) -> None:
        if not lock_token:
            return

        redis_client = self.get_redis_client()
        if redis_client is None:
            return

        lua_script = """
local key = KEYS[1]
local token = ARGV[1]
if redis.call('GET', key) == token then
  return redis.call('DEL', key)
end
return 0
"""
        # 自分が取得したロックだけを消すため、GET と DEL を Lua で不可分に実行する。
        # TTL 切れ後に別プロセスが取り直したロックを誤って解放しないため。
        try:
            redis_client.eval(lua_script, 1, self.active_lock_key(job_key), lock_token)
        except Exception:
            logger.exception("Redis chat generation lock release failed.")

    # 指定したジョブキーに対して Redis アクティブジョブロックが存在するか確認する
    # Check if a Redis active job lock exists for the specified job key
    def has_active_lock(self, job_key: str) -> bool:
        redis_client = self.get_redis_client()
        if redis_client is None:
            return False
        try:
            return bool(redis_client.exists(self.active_lock_key(job_key)))
        except Exception:
            logger.exception("Redis chat generation lock existence check failed.")
            return False

    # 所有プロセス以外が取得したロックを強制的に削除する（応答不能なワーカー対策）
    # Force-delete an active lock held by an unresponsive worker
    def force_release_active_job_lock(self, job_key: str) -> None:
        redis_client = self.get_redis_client()
        if redis_client is None:
            return
        try:
            redis_client.delete(self.active_lock_key(job_key))
        except Exception:
            logger.exception("Redis chat generation lock force release failed.")

    # 指定ジョブに対する停止要求マーカーが立っているかを確認する
    # Check whether a stop-request marker is set for the specified job
    def is_remote_cancel_requested(self, job_key: str) -> bool:
        redis_client = self.get_redis_client()
        if redis_client is None:
            return False
        try:
            return bool(redis_client.exists(self.cancel_request_key(job_key)))
        except Exception:
            logger.exception("Redis chat generation cancel-request check failed.")
            return False

    # 停止要求マーカーを削除する（新しい生成ジョブが古い要求で止まらないようにする）
    # Clear the stop-request marker so a new job is not aborted by a stale request
    def clear_remote_cancel_request(self, job_key: str) -> None:
        redis_client = self.get_redis_client()
        if redis_client is None:
            return
        try:
            redis_client.delete(self.cancel_request_key(job_key))
        except Exception:
            logger.exception("Redis chat generation cancel-request clear failed.")

    # 停止要求を Pub/Sub で配信し、ジョブを所有するワーカーの停止完了を待つ
    # Broadcast the stop request and wait for the owning worker to release the lock
    def request_remote_cancel(self, job_key: str) -> bool:
        redis_client = self.get_redis_client()
        if redis_client is None:
            return False
        if not self.has_active_lock(job_key):
            return False

        # マーカーは Pub/Sub 通知を取りこぼしたワーカーへの保険。
        # 生成ジョブ側が定期的に参照して自力で停止できるようにする。
        # The marker backs up the pub/sub notification: a worker that missed the message
        # still sees it while polling and stops on its own.
        try:
            redis_client.set(
                self.cancel_request_key(job_key),
                "1",
                ex=REMOTE_CANCEL_REQUEST_TTL_SECONDS,
            )
        except Exception:
            logger.exception("Redis chat generation cancel-request publish failed.")

        try:
            redis_client.publish(_CANCEL_CHANNEL_NAME, job_key)
        except Exception:
            logger.exception("Redis chat generation cancel broadcast failed.")
            return False

        deadline = time.monotonic() + self._remote_cancel_timeout_seconds
        while True:
            if not self.has_active_lock(job_key):
                return True
            if time.monotonic() >= deadline:
                break
            time.sleep(REMOTE_CANCEL_POLL_INTERVAL_SECONDS)

        # 所有ワーカーが応答しない場合でも、ロックを残すとルームが TTL 切れまで
        # 新規生成を拒否し続ける。マーカーは残すので、生きていれば後から自力停止する。
        # If the owning worker never answers, leaving the lock would reject new generations
        # until it expires. Drop it; the marker stays so a live owner still stops itself.
        logger.warning(
            "Timed out waiting for the owning worker to cancel a chat generation job.",
            extra={"job_key": job_key},
        )
        self.force_release_active_job_lock(job_key)
        return True

    # 他ワーカーからの停止要求を購読し、自プロセスのジョブをキャンセルするループ
    # Subscribe to stop requests from other workers and cancel this process's jobs
    def run_cancel_listener(self) -> None:
        redis_client = self.get_redis_client()
        if redis_client is None:
            self.release_cancel_listener_slot()
            return

        pubsub = None
        try:
            pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(_CANCEL_CHANNEL_NAME)
            while True:
                message = pubsub.get_message(timeout=1.0)
                if message and message.get("type") == "message":
                    job_key = decode_redis_text(message.get("data"))
                    if job_key:
                        self._cancel_local_job(job_key)
                # 実行中ジョブが無くなったら購読を畳み、次の生成開始時に再購読する。
                # Stop subscribing once no job is running; the next job restarts the listener.
                if self.release_cancel_listener_slot_if_idle():
                    return
        except Exception:
            logger.exception("Chat generation cancel listener stopped unexpectedly.")
            self.release_cancel_listener_slot()
        finally:
            if pubsub is not None:
                try:
                    pubsub.close()
                except Exception:
                    logger.exception("Failed to close the chat generation cancel listener.")

    # 購読スレッドの登録を解除する
    # Deregister the listener thread slot
    def release_cancel_listener_slot(self) -> None:
        with self._cancel_listener_lock:
            if self._cancel_listener_thread is threading.current_thread():
                self._cancel_listener_thread = None

    # 実行中ジョブが無い場合にだけ購読スレッドの登録を解除する
    # Deregister the listener thread slot only while no job is running
    def release_cancel_listener_slot_if_idle(self) -> bool:
        with self._cancel_listener_lock:
            if self._has_running_local_jobs():
                return False
            if self._cancel_listener_thread is threading.current_thread():
                self._cancel_listener_thread = None
            return True

    # 停止要求を購読するスレッドが起動していることを保証する
    # Ensure the thread subscribing to stop requests is running
    def ensure_cancel_listener(self) -> None:
        redis_client = self.get_redis_client()
        if redis_client is None or not hasattr(redis_client, "pubsub"):
            return
        with self._cancel_listener_lock:
            thread = self._cancel_listener_thread
            if thread is not None and thread.is_alive():
                return
            thread = threading.Thread(
                target=self.run_cancel_listener,
                name="chat-generation-cancel-listener",
                daemon=True,
            )
            self._cancel_listener_thread = thread
            thread.start()

    # 別プロセスが書いたイベントを Redis から読み、SSE として配信できる形で流す
    # Read events another process wrote and stream them in the shape SSE expects
    def iter_distributed_events(
        self,
        job_key: str,
        *,
        after_sequence_id: int = 0,
        has_active_generation: Callable[[str], bool],
    ) -> Iterator[ChatGenerationEvent | None]:
        redis_client = self.get_redis_client()
        if redis_client is None:
            return

        cursor = max(after_sequence_id, 0)

        terminal_seen = False
        for event in self.read_events(job_key, after_sequence_id=cursor):
            cursor = max(cursor, event.sequence_id)
            if event.event in _TERMINAL_EVENTS:
                terminal_seen = True
            yield event
        if terminal_seen:
            return

        if not has_active_generation(job_key):
            return

        channel = self.event_channel_name(job_key)
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        idle_deadline = time.monotonic() + self._distributed_stream_idle_timeout_seconds
        next_heartbeat_at = time.monotonic() + self._sse_heartbeat_seconds
        try:
            pubsub.subscribe(channel)

            # subscribe 直前に list へ書かれたイベントを先に読む。
            # pub/sub は購読前のメッセージを保持しないため、この二段読みで取りこぼしを埋める。
            for event in self.read_events(job_key, after_sequence_id=cursor):
                cursor = max(cursor, event.sequence_id)
                if event.event in _TERMINAL_EVENTS:
                    terminal_seen = True
                idle_deadline = time.monotonic() + self._distributed_stream_idle_timeout_seconds
                yield event
            if terminal_seen:
                return

            while True:
                message = pubsub.get_message(timeout=1.0)
                if message and message.get("type") == "message":
                    raw_data = decode_redis_text(message.get("data"))
                    if raw_data is not None:
                        deserialized_event = self.deserialize_event(raw_data)
                        if deserialized_event is not None and deserialized_event.sequence_id > cursor:
                            cursor = deserialized_event.sequence_id
                            idle_deadline = (
                                time.monotonic() + self._distributed_stream_idle_timeout_seconds
                            )
                            yield deserialized_event
                            next_heartbeat_at = time.monotonic() + self._sse_heartbeat_seconds
                            if deserialized_event.event in _TERMINAL_EVENTS:
                                return
                    continue

                if (
                    self._sse_heartbeat_seconds
                    and time.monotonic() >= next_heartbeat_at
                ):
                    next_heartbeat_at = time.monotonic() + self._sse_heartbeat_seconds
                    yield None

                if not has_active_generation(job_key):
                    # ロック消滅直後は pub/sub の最後の通知がまだ届かないことがあるため、
                    # 終了判定の前に list をもう一度読んで終端イベントを回収する。
                    saw_new = False
                    for event in self.read_events(job_key, after_sequence_id=cursor):
                        saw_new = True
                        cursor = max(cursor, event.sequence_id)
                        idle_deadline = (
                            time.monotonic() + self._distributed_stream_idle_timeout_seconds
                        )
                        yield event
                        if event.event in _TERMINAL_EVENTS:
                            return
                    if not saw_new:
                        return
                    continue

                if time.monotonic() >= idle_deadline:
                    logger.warning(
                        "Timed out waiting for distributed chat generation events.",
                        extra={"job_key": job_key, "after_sequence_id": after_sequence_id},
                    )
                    raise ChatGenerationStreamTimeoutError(
                        "応答ストリームが一定時間更新されなかったため接続を終了しました。再試行してください。"
                    )
        finally:
            try:
                pubsub.close()
            except Exception:
                logger.exception("Failed to close Redis pubsub for chat generation stream.")
