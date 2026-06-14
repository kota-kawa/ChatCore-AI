from __future__ import annotations

import logging
import json
import os
import inspect
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
from services.generative_ui import normalize_response_with_artifacts

from .llm import (
    LlmAuthenticationError,
    LlmConfigurationError,
    LlmRateLimitError,
    LlmRetryableProviderError,
    LlmServiceError,
    get_llm_response_stream,
    is_retryable_llm_error,
)
from .web_search import (
    build_web_search_trace_markdown,
    combine_web_search_results,
    get_web_search_tool_definition,
    is_web_search_enabled,
    maybe_augment_messages_with_web_search,
    search_brave_llm_context,
    WebSearchQuotaExceeded,
    WebSearchResult,
)

logger = logging.getLogger(__name__)

JOB_RETENTION_SECONDS = 300
DEFAULT_ACTIVE_JOB_LOCK_TTL_SECONDS = 900
DEFAULT_DISTRIBUTED_STREAM_IDLE_TIMEOUT_SECONDS = 60
DEFAULT_CHAT_AGENT_MAX_STEPS = 10
CHAT_AGENT_MAX_STEPS_LIMIT = 10
# 出力開始前の一時的なプロバイダ障害を再試行する回数と待機時間
# Retry budget and backoff for transient provider failures before any output is emitted.
DEFAULT_LLM_STREAM_MAX_RETRIES = 2
LLM_STREAM_RETRY_BASE_DELAY_SECONDS = 0.5
LLM_STREAM_RETRY_MAX_DELAY_SECONDS = 8.0
_ACTIVE_JOB_LOCK_KEY_PREFIX = "chat_generation:active"
_EVENT_STREAM_KEY_PREFIX = "chat_generation:events"
_EVENT_CHANNEL_KEY_PREFIX = "chat_generation:events:channel"
_TERMINAL_EVENTS = {"done", "error", "aborted"}


# 日本語: build streaming parts update の組み立て処理を担当します。
# English: Handle building for build streaming parts update.
def _build_streaming_parts_update(raw_text: str) -> dict[str, Any] | None:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if "chatcore-artifact" not in raw_text and "chatcore-buttons" not in raw_text:
        return None

    normalized_response = normalize_response_with_artifacts(raw_text, allow_fallback=False)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if normalized_response.validation_errors or not normalized_response.parts:
        return None

    if not any(part.get("type") != "text" for part in normalized_response.parts):
        return None

    return {
        "response": normalized_response.text,
        "parts": normalized_response.parts,
    }


# 日本語: get chat agent max steps の取得処理を担当します。
# English: Handle fetching for get chat agent max steps.
def _get_chat_agent_max_steps() -> int:
    raw = os.environ.get("CHAT_AGENT_MAX_STEPS")
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if raw is None:
        return DEFAULT_CHAT_AGENT_MAX_STEPS
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_CHAT_AGENT_MAX_STEPS
    return min(max(value, 1), CHAT_AGENT_MAX_STEPS_LIMIT)


# 日本語: get llm stream max retries の取得処理を担当します。
# English: Handle fetching for get llm stream max retries.
def _get_llm_stream_max_retries() -> int:
    raw = os.environ.get("LLM_STREAM_MAX_RETRIES")
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if raw is None:
        return DEFAULT_LLM_STREAM_MAX_RETRIES
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LLM_STREAM_MAX_RETRIES
    return max(value, 0)


# 日本語: llm stream retry delay に関する処理の入口です。
# English: Entry point for logic related to llm stream retry delay.
def _llm_stream_retry_delay(exc: BaseException, attempt: int) -> float:
    # サーバー指定のretry_afterを優先し、なければ指数バックオフ（上限あり）を用いる
    # Prefer server-provided retry_after, otherwise use capped exponential backoff.
    retry_after = getattr(exc, "retry_after_seconds", None)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if isinstance(retry_after, int) and retry_after > 0:
        return min(float(retry_after), LLM_STREAM_RETRY_MAX_DELAY_SECONDS)
    delay = LLM_STREAM_RETRY_BASE_DELAY_SECONDS * (2 ** attempt)
    return min(delay, LLM_STREAM_RETRY_MAX_DELAY_SECONDS)


# 日本語: parse tool calls chunk の解析処理を担当します。
# English: Handle parsing for parse tool calls chunk.
def _parse_tool_calls_chunk(chunk: str) -> list[dict[str, Any]] | None:
    stripped = chunk.strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not stripped.startswith("[") or '"function"' not in stripped:
        return None
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        loaded = json.loads(stripped)
    except Exception:
        return None
    if not isinstance(loaded, list):
        return None
    tool_calls: list[dict[str, Any]] = []
    for item in loaded:
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        if not function.get("name"):
            continue
        tool_calls.append(item)
    return tool_calls or None


# 日本語: normalized search key に関する処理の入口です。
# English: Entry point for logic related to normalized search key.
def _normalized_search_key(query: Any, freshness: Any = "") -> tuple[str, str]:
    normalized_query = " ".join(str(query or "").split())
    normalized_freshness = str(freshness or "").strip()
    return (normalized_query.casefold(), normalized_freshness)


# 日本語: normalize tool call の正規化処理を担当します。
# English: Handle normalizing for normalize tool call.
def _normalize_tool_call(tool_call: dict[str, Any], *, step: int, index: int) -> dict[str, Any]:
    normalized = dict(tool_call)
    function = dict(normalized.get("function") or {})
    normalized["function"] = function
    normalized["type"] = normalized.get("type") or "function"
    normalized["id"] = str(normalized.get("id") or f"call-{step}-{index}")
    function["name"] = str(function.get("name") or "")
    function["arguments"] = str(function.get("arguments") or "{}")
    return normalized


# 日本語: tool result message に関する処理の入口です。
# English: Entry point for logic related to tool result message.
def _tool_result_message(tool_call: dict[str, Any], content: dict[str, Any] | str) -> dict[str, Any]:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return {
        "role": "tool",
        "tool_call_id": tool_call.get("id"),
        "name": tool_call.get("function", {}).get("name", ""),
        "content": content,
    }


# 日本語: page read trace step に関する処理の入口です。
# English: Entry point for logic related to page read trace step.
def _page_read_trace_step(result: WebSearchResult | None) -> dict[str, str] | None:
    # 検索結果から重要なページ本文を取得できた場合に、回答ステップとして可視化する
    # Surface a trace step when full page text was successfully read from result URLs.
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if result is None:
        return None
    read_count = sum(1 for source in result.sources if source.page_text)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not read_count:
        return None
    return {
        "title": "重要なページを精読",
        "detail": f"{read_count}件のページ本文を取得して回答に反映しました。",
    }


# 日本語: web search result tool payload に関する処理の入口です。
# English: Entry point for logic related to web search result tool payload.
def _web_search_result_tool_payload(
    result: WebSearchResult,
    *,
    cached: bool = False,
) -> dict[str, Any]:
    return {
        "status": "completed",
        "cached": cached,
        "query": result.query,
        "searched_at": result.searched_at,
        "source_count": len(result.sources),
        "sources": [
            {
                "url": source.url,
                "title": source.title,
                "hostname": source.hostname,
                "age": source.age,
                "snippets": list(source.snippets),
                **({"page_text": source.page_text} if source.page_text else {}),
            }
            for source in result.sources
        ],
    }


# 日本語: ChatGenerationAlreadyRunningError として扱う例外情報を表します。
# English: Represent exception details handled as ChatGenerationAlreadyRunningError.
class ChatGenerationAlreadyRunningError(RuntimeError):
    pass


# 日本語: ChatGenerationStreamTimeoutError として扱う例外情報を表します。
# English: Represent exception details handled as ChatGenerationStreamTimeoutError.
class ChatGenerationStreamTimeoutError(RuntimeError):
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.payload = {
            "message": message,
            "retryable": True,
        }


# 日本語: ChatGenerationEvent に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatGenerationEvent.
@dataclass(frozen=True)
class ChatGenerationEvent:
    sequence_id: int
    event: str
    payload: dict[str, Any]


# 日本語: ChatGenerationJob に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatGenerationJob.
class ChatGenerationJob:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(
        self,
        *,
        conversation_messages: list[dict[str, Any]],
        model: str,
        persist_response: Callable[..., dict[str, Any] | None],
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

    # 日本語: persist generated response に関する処理の入口です。
    # English: Entry point for logic related to persist generated response.
    def _persist_generated_response(
        self,
        response: str,
        message_parts: list[dict[str, Any]] | None,
    ) -> dict[str, Any] | None:
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            signature = inspect.signature(self._persist_response)
            accepts_message_parts = (
                "message_parts" in signature.parameters
                or any(
                    parameter.kind == inspect.Parameter.VAR_KEYWORD
                    for parameter in signature.parameters.values()
                )
            )
        except (TypeError, ValueError):
            accepts_message_parts = False

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if accepts_message_parts:
            return self._persist_response(response, message_parts=message_parts)
        return self._persist_response(response)

    # 日本語: start に関する処理の入口です。
    # English: Entry point for logic related to start.
    def start(self) -> None:
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self._future is not None:
            return
        self._future = submit_background_task(self._run)

    # 日本語: cancel に関する処理の入口です。
    # English: Entry point for logic related to cancel.
    def cancel(self) -> None:
        """生成をキャンセルし、aborted イベントを発行して完了とする."""
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self.is_done:
            return
        self._cancelled = True
        self._publish("aborted", {}, done=True)

    # 日本語: wait に関する処理の入口です。
    # English: Entry point for logic related to wait.
    def wait(self, timeout: float | None = None) -> bool:
        future = self._future
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if future is None:
            return self.is_done
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            future.result(timeout=timeout)
        except TimeoutError:
            return self.is_done
        except Exception:
            return self.is_done
        return self.is_done

    # 日本語: iter events に関する処理の入口です。
    # English: Entry point for logic related to iter events.
    def iter_events(self, *, after_sequence_id: int = 0) -> Iterator[ChatGenerationEvent]:
        cursor = 0
        # 日本語: 条件が満たされている間、同じ処理を継続します。
        # English: Continue the same work while the condition remains true.
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

    # 日本語: publish に関する処理の入口です。
    # English: Entry point for logic related to publish.
    def _publish(self, event: str, payload: dict[str, Any], *, done: bool = False) -> None:
        callback: Callable[[], None] | None = None
        event_callback = self._on_event
        published_event: ChatGenerationEvent | None = None
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if event_callback is not None and published_event is not None:
            try:
                event_callback(published_event)
            except Exception:
                logger.exception("Failed to publish distributed chat generation event.")
        if callback is not None:
            callback()

    # 日本語: mark done に関する処理の入口です。
    # English: Entry point for logic related to mark done.
    def _mark_done(self) -> Callable[[], None] | None:
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self.is_done:
            return None
        self.is_done = True
        self.finished_at = time.monotonic()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self._on_finished_called or self._on_finished is None:
            return None
        self._on_finished_called = True
        return self._on_finished

    # 日本語: handle error のハンドリング処理を担当します。
    # English: Handle handling for handle error.
    def _handle_error(
        self,
        message: str,
        payload: dict[str, Any],
        *,
        invoke_error_callback: bool = False,
    ) -> None:
        self.error_message = message
        self._publish("error", payload, done=True)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not invoke_error_callback or self._on_error is None:
            return
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            self._on_error()
        except Exception:
            logger.exception("Failed to run chat generation error callback.")

    # 日本語: sleep with cancel に関する処理の入口です。
    # English: Entry point for logic related to sleep with cancel.
    def _sleep_with_cancel(self, delay: float) -> bool:
        # キャンセルを監視しつつ待機し、キャンセルされた場合は True を返す
        # Sleep while watching for cancellation; return True if cancelled.
        deadline = time.monotonic() + max(delay, 0.0)
        # 日本語: 条件が満たされている間、同じ処理を継続します。
        # English: Continue the same work while the condition remains true.
        while time.monotonic() < deadline:
            if self._cancelled:
                return True
            time.sleep(min(0.1, max(deadline - time.monotonic(), 0.0)))
        return self._cancelled

    # 日本語: iter llm stream with retry に関する処理の入口です。
    # English: Entry point for logic related to iter llm stream with retry.
    def _iter_llm_stream_with_retry(
        self,
        current_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> Iterator[str]:
        # 出力開始前の一時的なプロバイダ障害のみ再試行し、内部エラー表示を抑制する。
        # 一度でもチャンクを送出した後は重複出力を避けるため再試行しない。
        # Retry transient provider failures only before any chunk is emitted, so brief
        # upstream blips do not surface as an internal error. Never retry once a chunk has
        # been emitted, to avoid duplicated or garbled output.
        max_retries = _get_llm_stream_max_retries()
        attempt = 0
        # 日本語: 条件が満たされている間、同じ処理を継続します。
        # English: Continue the same work while the condition remains true.
        while True:
            emitted = False
            try:
                for chunk in get_llm_response_stream(
                    current_messages, self._model, tools=tools
                ):
                    emitted = True
                    yield chunk
                return
            except LlmRetryableProviderError as exc:
                # レート制限はサーバー指定の待機を尊重するため別ハンドラに委ねる
                # Rate limits are handled separately to honor server-provided backoff.
                if (
                    emitted
                    or isinstance(exc, LlmRateLimitError)
                    or attempt >= max_retries
                    or self._cancelled
                ):
                    raise
                delay = _llm_stream_retry_delay(exc, attempt)
                attempt += 1
                logger.warning(
                    "Retrying LLM stream after transient error "
                    "(attempt %s/%s, model=%s, delay=%.2fs): %s",
                    attempt,
                    max_retries,
                    self._model,
                    delay,
                    exc.__class__.__name__,
                )
                if self._sleep_with_cancel(delay):
                    raise

    # 日本語: run の実行処理を担当します。
    # English: Handle running for run.
    def _run(self) -> None:
        chunks: list[str] = []
        last_streaming_parts_signature: str | None = None
        web_search_results: list[WebSearchResult] = []
        web_search_results_by_key: dict[tuple[str, str], WebSearchResult] = {}
        web_search_trace_steps: list[dict[str, str]] = []
        current_messages = [dict(m) for m in self._conversation_messages]
        suppress_next_generation_started = False
        max_steps = _get_chat_agent_max_steps()
        step_count = 0

        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            augmentation = maybe_augment_messages_with_web_search(
                current_messages,
                self._model,
                publish_event=self._publish,
            )
            current_messages = augmentation.messages
            if augmentation.result is not None:
                web_search_trace_steps.extend(
                    [
                        {
                            "title": "検索が必要か判断",
                            "detail": "最新情報が必要な可能性を確認しました。",
                        },
                        {
                            "title": f"Web検索: {augmentation.result.query}",
                            "detail": f"{len(augmentation.result.sources)}件の候補を取得しました。",
                        },
                        {
                            "title": "検索結果を確認",
                            "detail": "取得した情報を回答用の文脈に追加しました。",
                        },
                    ]
                )
                page_read_step = _page_read_trace_step(augmentation.result)
                if page_read_step is not None:
                    web_search_trace_steps.append(page_read_step)
                web_search_results.append(augmentation.result)
                web_search_results_by_key[
                    _normalized_search_key(
                        augmentation.result.query,
                        augmentation.result.freshness,
                    )
                ] = augmentation.result
                step_count += 1
            elif augmentation.status in {"failed", "no_sources"}:
                step_count += 1
                web_search_trace_steps.append(
                    {
                        "title": "Web検索を試行",
                        "detail": "検索結果を回答に使える形では取得できませんでした。",
                    }
                )
            suppress_next_generation_started = augmentation.status == "failed"

            if self._cancelled:
                return

            web_search_tool = get_web_search_tool_definition()

            while step_count < max_steps:
                if self._cancelled:
                    return

                remaining_steps = max_steps - step_count
                allow_tools = remaining_steps >= 3 and is_web_search_enabled()
                tools = [web_search_tool] if allow_tools else None
                llm_step = step_count + 1

                if not suppress_next_generation_started:
                    self._publish(
                        "response_generation_started",
                        {"step": llm_step, "max_steps": max_steps},
                    )
                suppress_next_generation_started = False
                step_count += 1

                tool_calls_buffer: list[dict[str, Any]] = []
                for chunk in self._iter_llm_stream_with_retry(current_messages, tools=tools):
                    if self._cancelled:
                        return
                    if not chunk:
                        continue

                    parsed_tool_calls = _parse_tool_calls_chunk(chunk) if allow_tools else None
                    if parsed_tool_calls is not None:
                        tool_calls_buffer.extend(parsed_tool_calls)
                        continue

                    if not chunks:
                        combined_web_search_result = combine_web_search_results(web_search_results)
                        if web_search_trace_steps or combined_web_search_result is not None:
                            web_search_trace_steps.append(
                                {
                                    "title": "回答を作成",
                                    "detail": "検索結果と会話文脈を統合して回答しました。",
                                }
                            )
                        trace_block = build_web_search_trace_markdown(
                            combined_web_search_result,
                            steps=web_search_trace_steps,
                        )
                        if trace_block:
                            chunk = f"{trace_block}\n\n{chunk}"

                    chunks.append(chunk)
                    self._publish("chunk", {"text": chunk})
                    streaming_parts_update = _build_streaming_parts_update("".join(chunks))
                    if streaming_parts_update is not None:
                        streaming_parts_signature = json.dumps(
                            streaming_parts_update,
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        if streaming_parts_signature != last_streaming_parts_signature:
                            last_streaming_parts_signature = streaming_parts_signature
                            self._publish("response_parts_updated", streaming_parts_update)

                if not tool_calls_buffer:
                    break

                normalized_tool_calls = [
                    _normalize_tool_call(tool_call, step=llm_step, index=index)
                    for index, tool_call in enumerate(tool_calls_buffer, start=1)
                ]
                assistant_tool_call_msg = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": normalized_tool_calls,
                }
                current_messages.append(assistant_tool_call_msg)

                for tc in normalized_tool_calls:
                    func_name = tc.get("function", {}).get("name")
                    if func_name != "web_search":
                        current_messages.append(
                            _tool_result_message(
                                tc,
                                {
                                    "status": "unsupported_tool",
                                    "message": f"Unsupported tool: {func_name}",
                                },
                            )
                        )
                        continue

                    args_raw = tc.get("function", {}).get("arguments", "{}")
                    try:
                        args = json.loads(args_raw)
                    except Exception:
                        args = {}
                    if not isinstance(args, dict):
                        args = {}

                    query = args.get("query")
                    freshness = args.get("freshness", "")
                    if not query:
                        current_messages.append(
                            _tool_result_message(
                                tc,
                                {
                                    "status": "invalid_arguments",
                                    "message": "Search query is empty.",
                                },
                            )
                        )
                        continue

                    if max_steps - step_count <= 1:
                        current_messages.append(
                            _tool_result_message(
                                tc,
                                {
                                    "status": "step_limit_reached",
                                    "message": (
                                        "The web search step limit has been reached. "
                                        "Answer using the information already available."
                                    ),
                                },
                            )
                        )
                        continue

                    step_count += 1
                    query_text = str(query)
                    freshness_text = str(freshness or "")
                    search_key = _normalized_search_key(query_text, freshness_text)
                    cached_result = web_search_results_by_key.get(search_key)

                    self._publish(
                        "web_search_started",
                        {
                            "query": query_text,
                            "reason": "Model-requested search",
                            "step": step_count,
                            "max_steps": max_steps,
                            "cached": cached_result is not None,
                        },
                    )
                    if cached_result is not None:
                        web_search_trace_steps.extend(
                            [
                                {
                                    "title": f"検索結果を再利用: {cached_result.query}",
                                    "detail": "同じ検索条件の結果を再利用しました。",
                                },
                                {
                                    "title": "検索結果を確認",
                                    "detail": "再利用した情報で不足がないか確認しました。",
                                },
                            ]
                        )
                        self._publish(
                            "web_search_completed",
                            {
                                "query": cached_result.query,
                                "source_count": len(cached_result.sources),
                                "step": step_count,
                                "max_steps": max_steps,
                                "cached": True,
                            },
                        )
                        current_messages.append(
                            _tool_result_message(
                                tc,
                                _web_search_result_tool_payload(cached_result, cached=True),
                            )
                        )
                        continue

                    try:
                        result = search_brave_llm_context(query_text, freshness=freshness_text)
                        web_search_results_by_key[search_key] = result
                        search_step_title = "追加検索" if web_search_results else "Web検索"
                        web_search_trace_steps.extend(
                            [
                                {
                                    "title": f"{search_step_title}: {result.query}",
                                    "detail": f"{len(result.sources)}件の候補を取得しました。",
                                },
                                {
                                    "title": "検索結果を確認",
                                    "detail": "取得した情報で回答に足りるか確認しました。",
                                },
                            ]
                        )
                        page_read_step = _page_read_trace_step(result)
                        if page_read_step is not None:
                            web_search_trace_steps.append(page_read_step)
                        if result.has_sources:
                            web_search_results.append(result)
                        self._publish(
                            "web_search_completed",
                            {
                                "query": result.query,
                                "source_count": len(result.sources),
                                "step": step_count,
                                "max_steps": max_steps,
                                "cached": False,
                            },
                        )
                        current_messages.append(
                            _tool_result_message(
                                tc,
                                _web_search_result_tool_payload(result),
                            )
                        )
                    except WebSearchQuotaExceeded as exc:
                        message = (
                            f"Web検索の月間上限（全体 {exc.limit} 回）に達しました。"
                            "検索なしで回答を続けます。"
                        )
                        web_search_trace_steps.append(
                            {
                                "title": f"Web検索を試行: {query_text}",
                                "detail": "月間上限に達したため検索結果を取得できませんでした。",
                            }
                        )
                        suppress_next_generation_started = True
                        self._publish(
                            "web_search_failed",
                            {
                                "query": query_text,
                                "message": message,
                                "retry_after_seconds": exc.retry_after_seconds,
                                "step": step_count,
                                "max_steps": max_steps,
                            },
                        )
                        current_messages.append(
                            _tool_result_message(
                                tc,
                                {
                                    "status": "quota_exceeded",
                                    "message": message,
                                    "retry_after_seconds": exc.retry_after_seconds,
                                },
                            )
                        )
                    except Exception:
                        logger.exception("Brave search via tool call failed.")
                        web_search_trace_steps.append(
                            {
                                "title": f"Web検索を試行: {query_text}",
                                "detail": "検索リクエストに失敗したため、取得済み情報で回答を続けました。",
                            }
                        )
                        suppress_next_generation_started = True
                        self._publish(
                            "web_search_failed",
                            {
                                "query": query_text,
                                "message": "Web検索に失敗しました。検索なしで回答を続けます。",
                                "step": step_count,
                                "max_steps": max_steps,
                            },
                        )
                        current_messages.append(
                            _tool_result_message(
                                tc,
                                {
                                    "status": "failed",
                                    "message": "Web search failed.",
                                },
                            )
                        )

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

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self._cancelled:
            return

        bot_reply = "".join(chunks)
        if not chunks:
            combined_web_search_result = combine_web_search_results(web_search_results)
            if web_search_trace_steps or combined_web_search_result is not None:
                web_search_trace_steps.append(
                    {
                        "title": "回答を作成",
                        "detail": "検索結果と会話文脈を統合して回答しました。",
                    }
                )
            trace_block = build_web_search_trace_markdown(
                combined_web_search_result,
                steps=web_search_trace_steps,
            )
            if trace_block:
                separator = "" if not bot_reply or trace_block.endswith("\n\n") else "\n\n"
                bot_reply = f"{trace_block}{separator}{bot_reply}"
        normalized_response = normalize_response_with_artifacts(
            bot_reply,
            recover_truncated=True,
        )
        if normalized_response.validation_errors:
            logger.warning(
                "One or more generated UI artifacts failed validation and were omitted.",
                extra={"validation_errors": normalized_response.validation_errors},
            )
        bot_reply = normalized_response.text
        message_parts = normalized_response.parts
        self.response = bot_reply

        try:
            persist_metadata = self._persist_generated_response(bot_reply, message_parts)
        except Exception:
            logger.exception("Failed to persist background chat response.")
            error_message = "応答は生成されましたが、履歴保存に失敗しました。"
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": True},
                invoke_error_callback=not bot_reply,
            )
            return

        done_payload: dict[str, Any] = {"response": bot_reply}
        if message_parts:
            done_payload["parts"] = message_parts
        if isinstance(persist_metadata, dict):
            done_payload.update(persist_metadata)
        self._publish("done", done_payload, done=True)


# 日本語: build generation key の組み立て処理を担当します。
# English: Handle building for build generation key.
def build_generation_key(*, chat_room_id: str, user_id: int | None = None, sid: str | None = None) -> str:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if user_id is not None:
        return f"user:{user_id}:{chat_room_id}"
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if sid is not None:
        return f"guest:{sid}:{chat_room_id}"
    raise ValueError("Either user_id or sid is required to build a generation key.")


# 日本語: ChatGenerationService に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ChatGenerationService.
class ChatGenerationService:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
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

    # 日本語: get redis client の取得処理を担当します。
    # English: Handle fetching for get redis client.
    def _get_redis_client(self) -> Any | None:
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self._redis_client_getter is not None:
            return self._redis_client_getter()
        return get_redis_client()

    # 日本語: active lock key に関する処理の入口です。
    # English: Entry point for logic related to active lock key.
    def _active_lock_key(self, job_key: str) -> str:
        return f"{_ACTIVE_JOB_LOCK_KEY_PREFIX}:{job_key}"

    # 日本語: event stream key に関する処理の入口です。
    # English: Entry point for logic related to event stream key.
    def _event_stream_key(self, job_key: str) -> str:
        return f"{_EVENT_STREAM_KEY_PREFIX}:{job_key}"

    # 日本語: event channel name に関する処理の入口です。
    # English: Entry point for logic related to event channel name.
    def _event_channel_name(self, job_key: str) -> str:
        return f"{_EVENT_CHANNEL_KEY_PREFIX}:{job_key}"

    # 日本語: serialize event のシリアライズ処理を担当します。
    # English: Handle serializing for serialize event.
    def _serialize_event(self, event: ChatGenerationEvent) -> str:
        return json.dumps(
            {
                "id": event.sequence_id,
                "event": event.event,
                "payload": event.payload,
            },
            ensure_ascii=False,
        )

    # 日本語: deserialize event のデシリアライズ処理を担当します。
    # English: Handle deserializing for deserialize event.
    def _deserialize_event(self, raw: str) -> ChatGenerationEvent | None:
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            loaded = json.loads(raw)
        except Exception:
            return None
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
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

    # 日本語: publish distributed event に関する処理の入口です。
    # English: Entry point for logic related to publish distributed event.
    def _publish_distributed_event(self, job_key: str, event: ChatGenerationEvent) -> None:
        redis_client = self._get_redis_client()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
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
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            pipeline = redis_client.pipeline()
            pipeline.rpush(stream_key, serialized)
            pipeline.expire(stream_key, ttl_seconds)
            pipeline.publish(channel, serialized)
            pipeline.execute()
        except Exception:
            logger.exception("Failed to publish chat generation event to Redis.")

    # 日本語: read distributed events の読み込み処理を担当します。
    # English: Handle reading for read distributed events.
    def _read_distributed_events(
        self,
        job_key: str,
        *,
        after_sequence_id: int = 0,
    ) -> list[ChatGenerationEvent]:
        redis_client = self._get_redis_client()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if redis_client is None:
            return []
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
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

    # 日本語: try acquire active job lock に関する処理の入口です。
    # English: Entry point for logic related to try acquire active job lock.
    def _try_acquire_active_job_lock(self, job_key: str) -> tuple[bool, str | None]:
        redis_client = self._get_redis_client()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if redis_client is None:
            return True, None

        lock_key = self._active_lock_key(job_key)
        lock_token = uuid.uuid4().hex
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
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

    # 日本語: release active job lock に関する処理の入口です。
    # English: Entry point for logic related to release active job lock.
    def _release_active_job_lock(self, job_key: str, lock_token: str | None) -> None:
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not lock_token:
            return

        redis_client = self._get_redis_client()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
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

    # 日本語: has distributed active lock に関する処理の入口です。
    # English: Entry point for logic related to has distributed active lock.
    def _has_distributed_active_lock(self, job_key: str) -> bool:
        redis_client = self._get_redis_client()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if redis_client is None:
            return False
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            return bool(redis_client.exists(self._active_lock_key(job_key)))
        except Exception:
            logger.exception("Redis chat generation lock existence check failed.")
            return False

    # 日本語: supports distributed streaming に関する処理の入口です。
    # English: Entry point for logic related to supports distributed streaming.
    def supports_distributed_streaming(self) -> bool:
        return self._get_redis_client() is not None

    # 日本語: reset in memory state に関する処理の入口です。
    # English: Entry point for logic related to reset in memory state.
    def reset_in_memory_state(self, *, cancel_running: bool = False) -> None:
        running_jobs: list[ChatGenerationJob] = []
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self._jobs_lock:
            if cancel_running:
                running_jobs = [
                    job
                    for job in self._jobs.values()
                    if not job.is_done
                ]
            self._jobs.clear()

        # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
        # English: Process each target item in order and accumulate the needed result.
        for job in running_jobs:
            job.cancel()

    # 日本語: wait for running jobs に関する処理の入口です。
    # English: Entry point for logic related to wait for running jobs.
    def wait_for_running_jobs(self, *, timeout: float | None = None) -> bool:
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self._jobs_lock:
            running_jobs = [job for job in self._jobs.values() if not job.is_done]

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
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

    # 日本語: cleanup expired jobs に関する処理の入口です。
    # English: Entry point for logic related to cleanup expired jobs.
    def _cleanup_expired_jobs(self, now: float | None = None) -> None:
        current_time = time.monotonic() if now is None else now
        expired_keys: list[str] = []

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self._jobs_lock:
            for key, job in self._jobs.items():
                if not job.is_done or job.finished_at is None:
                    continue
                if current_time - job.finished_at >= self._job_retention_seconds:
                    expired_keys.append(key)

            for key in expired_keys:
                self._jobs.pop(key, None)

    # 日本語: cancel generation job に関する処理の入口です。
    # English: Entry point for logic related to cancel generation job.
    def cancel_generation_job(self, job_key: str) -> bool:
        """指定ジョブをキャンセルし、キャンセルできたか否かを返す."""
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self._jobs_lock:
            job = self._jobs.get(job_key)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if job is None or job.is_done:
            return False
        job.cancel()
        return True

    # 日本語: has active generation に関する処理の入口です。
    # English: Entry point for logic related to has active generation.
    def has_active_generation(self, job_key: str) -> bool:
        self._cleanup_expired_jobs()
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self._jobs_lock:
            job = self._jobs.get(job_key)
            if job is not None:
                return not job.is_done
        return self._has_distributed_active_lock(job_key)

    # 日本語: has replayable generation に関する処理の入口です。
    # English: Entry point for logic related to has replayable generation.
    def has_replayable_generation(self, job_key: str) -> bool:
        self._cleanup_expired_jobs()
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self._jobs_lock:
            local_job = self._jobs.get(job_key)
            if local_job is not None:
                return True

        redis_client = self._get_redis_client()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if redis_client is None:
            return False
        try:
            return bool(redis_client.exists(self._event_stream_key(job_key)))
        except Exception:
            logger.exception("Redis chat generation replay-state check failed.")
            return False

    # 日本語: get generation job の取得処理を担当します。
    # English: Handle fetching for get generation job.
    def get_generation_job(self, job_key: str) -> ChatGenerationJob | None:
        self._cleanup_expired_jobs()
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self._jobs_lock:
            return self._jobs.get(job_key)

    # 日本語: iter generation events に関する処理の入口です。
    # English: Entry point for logic related to iter generation events.
    def iter_generation_events(
        self,
        job_key: str,
        *,
        after_sequence_id: int = 0,
    ) -> Iterator[ChatGenerationEvent]:
        job = self.get_generation_job(job_key)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if job is not None:
            yield from job.iter_events(after_sequence_id=after_sequence_id)
            return

        redis_client = self._get_redis_client()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
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

    # 日本語: start generation job に関する処理の入口です。
    # English: Entry point for logic related to start generation job.
    def start_generation_job(
        self,
        job_key: str,
        *,
        conversation_messages: list[dict[str, Any]],
        model: str,
        persist_response: Callable[..., dict[str, Any] | None],
        on_finished: Callable[[], None] | None = None,
        on_error: Callable[[], None] | None = None,
    ) -> ChatGenerationJob:
        self._cleanup_expired_jobs()
        acquired_lock, lock_token = self._try_acquire_active_job_lock(job_key)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not acquired_lock:
            raise ChatGenerationAlreadyRunningError(job_key)

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: finalize job に関する処理の入口です。
    # English: Entry point for logic related to finalize job.
    def _finalize_job(
        self,
        job_key: str,
        lock_token: str | None,
        *,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        self._release_active_job_lock(job_key, lock_token)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if on_finished is None:
            return
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            on_finished()
        except Exception:
            logger.exception("Failed to run chat generation finished callback.")


_default_chat_generation_service = ChatGenerationService()


# 日本語: get chat generation service の取得処理を担当します。
# English: Handle fetching for get chat generation service.
def get_chat_generation_service(request: Request = None) -> ChatGenerationService:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if request is not None:
        app = request.scope.get("app")
        state = getattr(app, "state", None)
        service = getattr(state, "chat_generation_service", None)
        if isinstance(service, ChatGenerationService):
            return service
    return _default_chat_generation_service


# 日本語: clear generation job state の初期化処理を担当します。
# English: Handle clearing for clear generation job state.
def clear_generation_job_state(*, cancel_running: bool = False) -> None:
    get_chat_generation_service().reset_in_memory_state(cancel_running=cancel_running)


# 日本語: cancel generation job に関する処理の入口です。
# English: Entry point for logic related to cancel generation job.
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


# 日本語: has active generation に関する処理の入口です。
# English: Entry point for logic related to has active generation.
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


# 日本語: get generation job の取得処理を担当します。
# English: Handle fetching for get generation job.
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


# 日本語: has replayable generation に関する処理の入口です。
# English: Entry point for logic related to has replayable generation.
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


# 日本語: iter generation events に関する処理の入口です。
# English: Entry point for logic related to iter generation events.
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


# 日本語: start generation job に関する処理の入口です。
# English: Entry point for logic related to start generation job.
def start_generation_job(
    job_key: str,
    *,
    conversation_messages: list[dict[str, Any]],
    model: str,
    persist_response: Callable[..., dict[str, Any] | None],
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
