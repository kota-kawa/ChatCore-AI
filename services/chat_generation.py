from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from services.cache import get_redis_client

from .llm import LlmConfigurationError, LlmServiceError, get_llm_response_stream

logger = logging.getLogger(__name__)

JOB_RETENTION_SECONDS = 300
DEFAULT_ACTIVE_JOB_LOCK_TTL_SECONDS = 900
_ACTIVE_JOB_LOCK_KEY_PREFIX = "chat_generation:active"


class ChatGenerationAlreadyRunningError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChatGenerationEvent:
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
    ) -> None:
        self._conversation_messages = [dict(message) for message in conversation_messages]
        self._model = model
        self._persist_response = persist_response
        self._on_finished = on_finished
        self._on_finished_called = False
        self._events: list[ChatGenerationEvent] = []
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._cancelled: bool = False
        self.response = ""
        self.error_message: str | None = None
        self.started_at = time.monotonic()
        self.finished_at: float | None = None
        self.is_done = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """生成をキャンセルし、aborted イベントを発行して完了とする."""
        callback: Callable[[], None] | None = None
        if self.is_done:
            return
        self._cancelled = True
        with self._condition:
            if not self.is_done:
                self._events.append(ChatGenerationEvent(event="aborted", payload={}))
                callback = self._mark_done()
                self._condition.notify_all()
        if callback is not None:
            callback()

    def wait(self, timeout: float | None = None) -> bool:
        thread = self._thread
        if thread is None:
            return self.is_done
        thread.join(timeout)
        return self.is_done

    def iter_events(self) -> Iterator[ChatGenerationEvent]:
        cursor = 0
        while True:
            with self._condition:
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
        with self._condition:
            self._events.append(ChatGenerationEvent(event=event, payload=payload))
            if done:
                callback = self._mark_done()
            self._condition.notify_all()
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

    def _run(self) -> None:
        chunks: list[str] = []
        try:
            for chunk in get_llm_response_stream(self._conversation_messages, self._model):
                if self._cancelled:
                    return
                if not chunk:
                    continue
                chunks.append(chunk)
                self._publish("chunk", {"text": chunk})
        except LlmConfigurationError as exc:
            if self._cancelled:
                return
            self.error_message = str(exc) or "LLM設定エラーが発生しました。"
            self._publish("error", {"message": self.error_message}, done=True)
            return
        except LlmServiceError:
            if self._cancelled:
                return
            self.error_message = "内部エラーが発生しました。"
            self._publish("error", {"message": self.error_message}, done=True)
            return
        except Exception:
            if self._cancelled:
                return
            logger.exception("Unexpected error while generating chat response.")
            self.error_message = "内部エラーが発生しました。"
            self._publish("error", {"message": self.error_message}, done=True)
            return

        if self._cancelled:
            return

        bot_reply = "".join(chunks)
        self.response = bot_reply

        try:
            self._persist_response(bot_reply)
        except Exception:
            logger.exception("Failed to persist background chat response.")
            self.error_message = "応答は生成されましたが、履歴保存に失敗しました。"
            self._publish("error", {"message": self.error_message}, done=True)
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
        redis_client_getter: Callable[[], Any | None] | None = None,
    ) -> None:
        self._job_retention_seconds = job_retention_seconds
        self._active_job_lock_ttl_seconds = max(active_job_lock_ttl_seconds, 1)
        self._redis_client_getter = redis_client_getter
        self._jobs: dict[str, ChatGenerationJob] = {}
        self._jobs_lock = threading.Lock()

    def _get_redis_client(self) -> Any | None:
        if self._redis_client_getter is not None:
            return self._redis_client_getter()
        return get_redis_client()

    def _active_lock_key(self, job_key: str) -> str:
        return f"{_ACTIVE_JOB_LOCK_KEY_PREFIX}:{job_key}"

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
            if job is not None and not job.is_done:
                return True
        return self._has_distributed_active_lock(job_key)

    def get_generation_job(self, job_key: str) -> ChatGenerationJob | None:
        self._cleanup_expired_jobs()
        with self._jobs_lock:
            return self._jobs.get(job_key)

    def start_generation_job(
        self,
        job_key: str,
        *,
        conversation_messages: list[dict[str, str]],
        model: str,
        persist_response: Callable[[str], None],
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
                on_finished=lambda: self._release_active_job_lock(job_key, lock_token),
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


def start_generation_job(
    job_key: str,
    *,
    conversation_messages: list[dict[str, str]],
    model: str,
    persist_response: Callable[[str], None],
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
    )
