from __future__ import annotations

import logging
import json
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from .background_executor import submit_background_task
from services.cache import get_redis_client

from .llm import (
    LlmAuthenticationError,
    LlmConfigurationError,
    LlmRateLimitError,
    LlmServiceError,
    get_llm_response_stream,
    is_retryable_llm_error,
)
from .web_search import maybe_augment_messages_with_web_search

logger = logging.getLogger(__name__)

JOB_RETENTION_SECONDS = 300
DEFAULT_ACTIVE_JOB_LOCK_TTL_SECONDS = 900
DEFAULT_DISTRIBUTED_STREAM_IDLE_TIMEOUT_SECONDS = 60
_ACTIVE_JOB_LOCK_KEY_PREFIX = "chat_generation:active"
_EVENT_STREAM_KEY_PREFIX = "chat_generation:events"
_EVENT_CHANNEL_KEY_PREFIX = "chat_generation:events:channel"
_TERMINAL_EVENTS = {"done", "error", "aborted"}


class ChatGenerationAlreadyRunningError(RuntimeError):
    pass


class ChatGenerationStreamTimeoutError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.payload = {
            "message": message,
            "retryable": True,
        }


@dataclass(frozen=True)
class ChatGenerationEvent:
    sequence_id: int
    event: str
    payload: dict[str, Any]


class ChatGenerationJob:
    def __init__(
        self,
        *,
        conversation_messages: list[dict[str, str]],
        model: str,
        persist_response: Callable[[str], None],
        on_finished: Callable[[], None] | None = None,
        on_event: Callable[[ChatGenerationEvent], None] | None = None,
        on_error: Callable[[], None] | None = None,
    ) -> None:
        self._conversation_messages = [dict(message) for message in conversation_messages]
        self._model = model
        self._persist_response = persist_response
        self._on_finished = on_finished
        self._on_finished_called = False
        self._on_event = on_event
        self._on_error = on_error
        self._events: list[ChatGenerationEvent] = []
        self._next_sequence_id = 1
        self._condition = threading.Condition()
        self._future: Future[None] | None = None
        self._cancelled: bool = False
        self.response = ""
        self.error_message: str | None = None
        self.started_at = time.monotonic()
        self.finished_at: float | None = None
        self.is_done = False

    def start(self) -> None:
        if self._future is not None:
            return
        self._future = submit_background_task(self._run)

    def cancel(self) -> None:
        """生成をキャンセルし、aborted イベントを発行して完了とする."""
        if self.is_done:
            return
        self._cancelled = True
        self._publish("aborted", {}, done=True)

    def wait(self, timeout: float | None = None) -> bool:
        future = self._future
        if future is None:
            return self.is_done
        try:
            future.result(timeout=timeout)
        except TimeoutError:
            return self.is_done
        except Exception:
            return self.is_done
        return self.is_done

    def iter_events(self, *, after_sequence_id: int = 0) -> Iterator[ChatGenerationEvent]:
        cursor = 0
        while True:
            with self._condition:
                while (
                    cursor < len(self._events)
                    and self._events[cursor].sequence_id <= after_sequence_id
                ):
                    cursor += 1

                while cursor >= len(self._events) and not self.is_done:
                    self._condition.wait(timeout=0.5)

                if cursor < len(self._events):
                    event = self._events[cursor]
                    cursor += 1
                elif self.is_done:
                    break
                else:
                    continue

            yield event

    def _publish(self, event: str, payload: dict[str, Any], *, done: bool = False) -> None:
        callback: Callable[[], None] | None = None
        event_callback = self._on_event
        published_event: ChatGenerationEvent | None = None
        with self._condition:
            if self.is_done:
                return
            sequence_id = self._next_sequence_id
            self._next_sequence_id += 1
            published_event = ChatGenerationEvent(
                sequence_id=sequence_id,
                event=event,
                payload=payload,
            )
            self._events.append(published_event)
            if done:
                callback = self._mark_done()
            self._condition.notify_all()
        if event_callback is not None and published_event is not None:
            try:
                event_callback(published_event)
            except Exception:
                logger.exception("Failed to publish distributed chat generation event.")
        if callback is not None:
            callback()

    def _mark_done(self) -> Callable[[], None] | None:
        if self.is_done:
            return None
        self.is_done = True
        self.finished_at = time.monotonic()
        if self._on_finished_called or self._on_finished is None:
            return None
        self._on_finished_called = True
        return self._on_finished

    def _handle_error(
        self,
        message: str,
        payload: dict[str, Any],
        *,
        invoke_error_callback: bool = False,
    ) -> None:
        self.error_message = message
        self._publish("error", payload, done=True)
        if not invoke_error_callback or self._on_error is None:
            return
        try:
            self._on_error()
        except Exception:
            logger.exception("Failed to run chat generation error callback.")

    def _run(self) -> None:
        chunks: list[str] = []
        try:
            conversation_messages = maybe_augment_messages_with_web_search(
                self._conversation_messages,
                self._model,
                publish_event=self._publish,
            )
            if self._cancelled:
                return
            for chunk in get_llm_response_stream(conversation_messages, self._model):
                if self._cancelled:
                    return
                if not chunk:
                    continue
                chunks.append(chunk)
                self._publish("chunk", {"text": chunk})
        except LlmConfigurationError as exc:
            if self._cancelled:
                return
            error_message = str(exc) or "LLM設定エラーが発生しました。"
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": False},
                invoke_error_callback=not chunks,
            )
            return
        except LlmAuthenticationError:
            if self._cancelled:
                return
            error_message = "LLMプロバイダ認証エラーが発生しました。設定を確認してください。"
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": False},
                invoke_error_callback=not chunks,
            )
            return
        except LlmRateLimitError as exc:
            if self._cancelled:
                return
            error_message = "AI提供元が混み合っています。時間をおいて再試行してください。"
            payload: dict[str, Any] = {
                "message": error_message,
                "retryable": True,
            }
            if exc.retry_after_seconds is not None:
                payload["retry_after_seconds"] = exc.retry_after_seconds
            self._handle_error(
                error_message,
                payload,
                invoke_error_callback=not chunks,
            )
            return
        except LlmServiceError as exc:
            if self._cancelled:
                return
            retryable = is_retryable_llm_error(exc)
            if retryable:
                error_message = "一時的な内部エラーが発生しました。時間をおいて再試行してください。"
            else:
                error_message = "内部エラーが発生しました。"
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": retryable},
                invoke_error_callback=not chunks,
            )
            return
        except Exception:
            if self._cancelled:
                return
            logger.exception("Unexpected error while generating chat response.")
            error_message = "内部エラーが発生しました。"
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": False},
                invoke_error_callback=not chunks,
            )
            return

        if self._cancelled:
            return

        bot_reply = "".join(chunks)
        self.response = bot_reply

        try:
            self._persist_response(bot_reply)
        except Exception:
            logger.exception("Failed to persist background chat response.")
            error_message = "応答は生成されましたが、履歴保存に失敗しました。"
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": True},
                invoke_error_callback=not bot_reply,
            )
            return

        self._publish("done", {"response": bot_reply}, done=True)


def build_generation_key(*, chat_room_id: str, user_id: int | None = None, sid: str | None = None) -> str:
    if user_id is not None:
        return f"user:{user_id}:{chat_room_id}"
    if sid is not None:
        return f"guest:{sid}:{chat_room_id}"
    raise ValueError("Either user_id or sid is required to build a generation key.")


class ChatGenerationService:
    def __init__(
        self,
        *,
        job_retention_seconds: int = JOB_RETENTION_SECONDS,
        active_job_lock_ttl_seconds: int = DEFAULT_ACTIVE_JOB_LOCK_TTL_SECONDS,
        distributed_stream_idle_timeout_seconds: float = (
            DEFAULT_DISTRIBUTED_STREAM_IDLE_TIMEOUT_SECONDS
        ),
        redis_client_getter: Callable[[], Any | None] | None = None,
    ) -> None:
        self._job_retention_seconds = job_retention_seconds
        self._active_job_lock_ttl_seconds = max(active_job_lock_ttl_seconds, 1)
        self._distributed_stream_idle_timeout_seconds = max(
            float(distributed_stream_idle_timeout_seconds),
            0.0,
        )
        self._redis_client_getter = redis_client_getter
        self._jobs: dict[str, ChatGenerationJob] = {}
        self._jobs_lock = threading.Lock()

    def _get_redis_client(self) -> Any | None:
        if self._redis_client_getter is not None:
            return self._redis_client_getter()
        return get_redis_client()

    def _active_lock_key(self, job_key: str) -> str:
        return f"{_ACTIVE_JOB_LOCK_KEY_PREFIX}:{job_key}"

    def _event_stream_key(self, job_key: str) -> str:
        return f"{_EVENT_STREAM_KEY_PREFIX}:{job_key}"

    def _event_channel_name(self, job_key: str) -> str:
        return f"{_EVENT_CHANNEL_KEY_PREFIX}:{job_key}"

    def _serialize_event(self, event: ChatGenerationEvent) -> str:
        return json.dumps(
            {
                "id": event.sequence_id,
                "event": event.event,
                "payload": event.payload,
            },
            ensure_ascii=False,
        )

    def _deserialize_event(self, raw: str) -> ChatGenerationEvent | None:
        try:
            loaded = json.loads(raw)
        except Exception:
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

    def _publish_distributed_event(self, job_key: str, event: ChatGenerationEvent) -> None:
        redis_client = self._get_redis_client()
        if redis_client is None:
            return
        serialized = self._serialize_event(event)
        stream_key = self._event_stream_key(job_key)
        channel = self._event_channel_name(job_key)
        ttl_seconds = max(
            self._job_retention_seconds + self._active_job_lock_ttl_seconds,
            self._job_retention_seconds,
            1,
        )
        try:
            pipeline = redis_client.pipeline()
            pipeline.rpush(stream_key, serialized)
            pipeline.expire(stream_key, ttl_seconds)
            pipeline.publish(channel, serialized)
            pipeline.execute()
        except Exception:
            logger.exception("Failed to publish chat generation event to Redis.")

    def _read_distributed_events(
        self,
        job_key: str,
        *,
        after_sequence_id: int = 0,
    ) -> list[ChatGenerationEvent]:
        redis_client = self._get_redis_client()
        if redis_client is None:
            return []
        try:
            raw_items = redis_client.lrange(self._event_stream_key(job_key), 0, -1)
        except Exception:
            logger.exception("Failed to read Redis chat generation event stream.")
            return []

        events: list[ChatGenerationEvent] = []
        for item in raw_items:
            if not isinstance(item, str):
                continue
            event = self._deserialize_event(item)
            if event is None:
                continue
            if event.sequence_id <= after_sequence_id:
                continue
            events.append(event)
        return events

    def _try_acquire_active_job_lock(self, job_key: str) -> tuple[bool, str | None]:
        redis_client = self._get_redis_client()
        if redis_client is None:
            return True, None

        lock_key = self._active_lock_key(job_key)
        lock_token = uuid.uuid4().hex
        try:
            acquired = redis_client.set(
                lock_key,
                lock_token,
                nx=True,
                ex=self._active_job_lock_ttl_seconds,
            )
        except Exception:
            logger.exception(
                "Redis chat generation lock acquisition failed; falling back to in-memory."
            )
            return True, None

        if acquired:
            return True, lock_token
        return False, None

    def _release_active_job_lock(self, job_key: str, lock_token: str | None) -> None:
        if not lock_token:
            return

        redis_client = self._get_redis_client()
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
        try:
            redis_client.eval(lua_script, 1, self._active_lock_key(job_key), lock_token)
        except Exception:
            logger.exception("Redis chat generation lock release failed.")

    def _has_distributed_active_lock(self, job_key: str) -> bool:
        redis_client = self._get_redis_client()
        if redis_client is None:
            return False
        try:
            return bool(redis_client.exists(self._active_lock_key(job_key)))
        except Exception:
            logger.exception("Redis chat generation lock existence check failed.")
            return False

    def supports_distributed_streaming(self) -> bool:
        return self._get_redis_client() is not None

    def reset_in_memory_state(self, *, cancel_running: bool = False) -> None:
        running_jobs: list[ChatGenerationJob] = []
        with self._jobs_lock:
            if cancel_running:
                running_jobs = [
                    job
                    for job in self._jobs.values()
                    if not job.is_done
                ]
            self._jobs.clear()

        for job in running_jobs:
            job.cancel()

    def wait_for_running_jobs(self, *, timeout: float | None = None) -> bool:
        with self._jobs_lock:
            running_jobs = [job for job in self._jobs.values() if not job.is_done]

        if not running_jobs:
            return True

        deadline = None if timeout is None else time.monotonic() + timeout
        all_done = True
        for job in running_jobs:
            if deadline is None:
                waited = job.wait(timeout=None)
            else:
                remaining = max(deadline - time.monotonic(), 0.0)
                waited = job.wait(timeout=remaining)
            if not waited:
                all_done = False
        return all_done

    def _cleanup_expired_jobs(self, now: float | None = None) -> None:
        current_time = time.monotonic() if now is None else now
        expired_keys: list[str] = []

        with self._jobs_lock:
            for key, job in self._jobs.items():
                if not job.is_done or job.finished_at is None:
                    continue
                if current_time - job.finished_at >= self._job_retention_seconds:
                    expired_keys.append(key)

            for key in expired_keys:
                self._jobs.pop(key, None)

    def cancel_generation_job(self, job_key: str) -> bool:
        """指定ジョブをキャンセルし、キャンセルできたか否かを返す."""
        with self._jobs_lock:
            job = self._jobs.get(job_key)
        if job is None or job.is_done:
            return False
        job.cancel()
        return True

    def has_active_generation(self, job_key: str) -> bool:
        self._cleanup_expired_jobs()
        with self._jobs_lock:
            job = self._jobs.get(job_key)
            if job is not None:
                return not job.is_done
        return self._has_distributed_active_lock(job_key)

    def has_replayable_generation(self, job_key: str) -> bool:
        self._cleanup_expired_jobs()
        with self._jobs_lock:
            local_job = self._jobs.get(job_key)
            if local_job is not None:
                return True

        redis_client = self._get_redis_client()
        if redis_client is None:
            return False
        try:
            return bool(redis_client.exists(self._event_stream_key(job_key)))
        except Exception:
            logger.exception("Redis chat generation replay-state check failed.")
            return False

    def get_generation_job(self, job_key: str) -> ChatGenerationJob | None:
        self._cleanup_expired_jobs()
        with self._jobs_lock:
            return self._jobs.get(job_key)

    def iter_generation_events(
        self,
        job_key: str,
        *,
        after_sequence_id: int = 0,
    ) -> Iterator[ChatGenerationEvent]:
        job = self.get_generation_job(job_key)
        if job is not None:
            yield from job.iter_events(after_sequence_id=after_sequence_id)
            return

        redis_client = self._get_redis_client()
        if redis_client is None:
            return

        cursor = max(after_sequence_id, 0)

        terminal_seen = False
        for event in self._read_distributed_events(job_key, after_sequence_id=cursor):
            cursor = max(cursor, event.sequence_id)
            if event.event in _TERMINAL_EVENTS:
                terminal_seen = True
            yield event
        if terminal_seen:
            return

        if not self.has_active_generation(job_key):
            return

        channel = self._event_channel_name(job_key)
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        idle_deadline = time.monotonic() + self._distributed_stream_idle_timeout_seconds
        try:
            pubsub.subscribe(channel)

            for event in self._read_distributed_events(job_key, after_sequence_id=cursor):
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
                    raw_data = message.get("data")
                    if isinstance(raw_data, bytes):
                        try:
                            raw_data = raw_data.decode("utf-8")
                        except Exception:
                            raw_data = None
                    if isinstance(raw_data, str):
                        event = self._deserialize_event(raw_data)
                        if event is not None and event.sequence_id > cursor:
                            cursor = event.sequence_id
                            idle_deadline = (
                                time.monotonic() + self._distributed_stream_idle_timeout_seconds
                            )
                            yield event
                            if event.event in _TERMINAL_EVENTS:
                                return
                    continue

                if not self.has_active_generation(job_key):
                    saw_new = False
                    for event in self._read_distributed_events(job_key, after_sequence_id=cursor):
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

    def start_generation_job(
        self,
        job_key: str,
        *,
        conversation_messages: list[dict[str, str]],
        model: str,
        persist_response: Callable[[str], None],
        on_finished: Callable[[], None] | None = None,
        on_error: Callable[[], None] | None = None,
    ) -> ChatGenerationJob:
        self._cleanup_expired_jobs()
        acquired_lock, lock_token = self._try_acquire_active_job_lock(job_key)
        if not acquired_lock:
            raise ChatGenerationAlreadyRunningError(job_key)

        with self._jobs_lock:
            existing_job = self._jobs.get(job_key)
            if existing_job is not None and not existing_job.is_done:
                self._release_active_job_lock(job_key, lock_token)
                raise ChatGenerationAlreadyRunningError(job_key)

            job = ChatGenerationJob(
                conversation_messages=conversation_messages,
                model=model,
                persist_response=persist_response,
                on_finished=lambda: self._finalize_job(
                    job_key,
                    lock_token,
                    on_finished=on_finished,
                ),
                on_event=lambda event: self._publish_distributed_event(job_key, event),
                on_error=on_error,
            )
            self._jobs[job_key] = job

        try:
            job.start()
        except Exception:
            with self._jobs_lock:
                self._jobs.pop(job_key, None)
            self._release_active_job_lock(job_key, lock_token)
            raise
        return job

    def _finalize_job(
        self,
        job_key: str,
        lock_token: str | None,
        *,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        self._release_active_job_lock(job_key, lock_token)
        if on_finished is None:
            return
        try:
            on_finished()
        except Exception:
            logger.exception("Failed to run chat generation finished callback.")


_default_chat_generation_service = ChatGenerationService()


def get_chat_generation_service(request: Request = None) -> ChatGenerationService:
    if request is not None:
        app = request.scope.get("app")
        state = getattr(app, "state", None)
        service = getattr(state, "chat_generation_service", None)
        if isinstance(service, ChatGenerationService):
            return service
    return _default_chat_generation_service


def clear_generation_job_state(*, cancel_running: bool = False) -> None:
    get_chat_generation_service().reset_in_memory_state(cancel_running=cancel_running)


def cancel_generation_job(
    job_key: str,
    *,
    service: ChatGenerationService | None = None,
) -> bool:
    target = (
        service
        if isinstance(service, ChatGenerationService)
        else get_chat_generation_service()
    )
    return target.cancel_generation_job(job_key)


def has_active_generation(
    job_key: str,
    *,
    service: ChatGenerationService | None = None,
) -> bool:
    target = (
        service
        if isinstance(service, ChatGenerationService)
        else get_chat_generation_service()
    )
    return target.has_active_generation(job_key)


def get_generation_job(
    job_key: str,
    *,
    service: ChatGenerationService | None = None,
) -> ChatGenerationJob | None:
    target = (
        service
        if isinstance(service, ChatGenerationService)
        else get_chat_generation_service()
    )
    return target.get_generation_job(job_key)


def has_replayable_generation(
    job_key: str,
    *,
    service: ChatGenerationService | None = None,
) -> bool:
    target = (
        service
        if isinstance(service, ChatGenerationService)
        else get_chat_generation_service()
    )
    return target.has_replayable_generation(job_key)


def iter_generation_events(
    job_key: str,
    *,
    after_sequence_id: int = 0,
    service: ChatGenerationService | None = None,
) -> Iterator[ChatGenerationEvent]:
    target = (
        service
        if isinstance(service, ChatGenerationService)
        else get_chat_generation_service()
    )
    return target.iter_generation_events(
        job_key,
        after_sequence_id=after_sequence_id,
    )


def start_generation_job(
    job_key: str,
    *,
    conversation_messages: list[dict[str, str]],
    model: str,
    persist_response: Callable[[str], None],
    on_finished: Callable[[], None] | None = None,
    on_error: Callable[[], None] | None = None,
    service: ChatGenerationService | None = None,
) -> ChatGenerationJob:
    target = (
        service
        if isinstance(service, ChatGenerationService)
        else get_chat_generation_service()
    )
    return target.start_generation_job(
        job_key,
        conversation_messages=conversation_messages,
        model=model,
        persist_response=persist_response,
        on_finished=on_finished,
        on_error=on_error,
    )
