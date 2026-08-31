from __future__ import annotations

import asyncio
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
from .chat_agent_budget import (
    DEFAULT_MAX_LLM_TURNS,
    DEFAULT_MAX_TOOL_CALLS,
    MAX_LLM_TURNS_LIMIT,
    MAX_TOOL_CALLS_LIMIT,
    AgentStepBudget,
)
from .chat_answer_continuation import (
    FinalAnswerContinuationStalledError,
    looks_like_restarted_answer,
    splice_restarted_answer,
    stream_final_answer_with_recovery,
    strip_continuation_overlap,
)
from .chat_generation_telemetry import ChatGenerationTelemetry
from .chat_input_budget import (
    compact_tool_messages,
    estimate_messages_chars,
    estimate_messages_tokens,
    get_final_answer_input_token_budget,
)
from services.cache import get_redis_client
from services.error_messages import ERROR_CHAT_EMPTY_RESPONSE
from services.generative_ui import (
    GenerativeUiMode,
    normalize_response_with_artifact_retry,
    normalize_response_with_artifacts,
)
from services.message_parts_display import (
    MAX_WEB_SEARCH_IMAGES_PER_REPLY,
    normalize_message_parts_for_display,
)

from .personal_knowledge import (
    PERSONAL_KNOWLEDGE_TOOL_NAME,
    get_personal_knowledge_tool_definition,
)
from .shared_prompt_lookup import (
    SHARED_PROMPT_TOOL_NAME,
    get_shared_prompt_tool_definition,
)
from .selected_reference_context import (
    PERSONAL_KNOWLEDGE_SOURCE,
    SHARED_PROMPT_SOURCE,
    SelectedReferenceLookupTrace,
)

from .llm import (
    LlmAuthenticationError,
    LlmConfigurationError,
    LlmInputLimitError,
    LlmOutputLimitError,
    LlmRateLimitError,
    LlmRetryableProviderError,
    LlmServiceError,
    get_llm_response,
    get_llm_response_stream,
    is_retryable_llm_error,
)
from .chat_research_notes import (
    append_step_note,
    build_final_answer_messages,
    build_research_loop_messages,
    build_research_wrapup_messages,
    extract_research_draft,
    parse_research_summary,
    parse_step_note,
    strip_internal_notes,
)
from .web_search import (
    WEB_SEARCH_MAX_CONTEXT_CHARS,
    WEB_SEARCH_TOOL_CONTEXT_MAX_CHARS,
    combine_web_search_results,
    create_web_evidence_context_budget,
    create_web_page_fetch_budget,
    get_web_search_tool_definition,
    inject_prior_web_search_context,
    is_web_search_enabled,
    maybe_augment_messages_with_web_search,
    resolve_web_search_citations,
    search_brave_llm_context,
    split_web_search_citation_stream_text,
    strip_web_search_citation_html,
    serialize_web_search_result,
    with_web_search_citations,
    WebSearchQuotaExceeded,
    WebEvidenceContextBudget,
    WebSearchResult,
    WEB_SEARCH_ERROR_QUOTA_EXCEEDED,
    WEB_SEARCH_ERROR_REQUEST_FAILED,
)
from .web_search_images import (
    append_web_search_image_parts,
    build_web_search_image_parts,
    build_web_search_image_parts_at_offsets,
    choose_web_search_images,
    find_next_streaming_image_insertion,
)
from .web_search_trace import (
    TraceStep,
    answer_step,
    build_web_search_trace_markdown,
    context_added_step,
    decision_step,
    page_reading_steps,
    review_step,
    search_failed_step,
    search_step,
    selected_reference_step,
    selected_reference_steps,
)

logger = logging.getLogger(__name__)

JOB_RETENTION_SECONDS = 300
DEFAULT_ACTIVE_JOB_LOCK_TTL_SECONDS = 900
DEFAULT_DISTRIBUTED_STREAM_IDLE_TIMEOUT_SECONDS = 60
DEFAULT_SSE_HEARTBEAT_SECONDS = 15.0
DEFAULT_CHAT_AGENT_MAX_STEPS = DEFAULT_MAX_LLM_TURNS + DEFAULT_MAX_TOOL_CALLS
CHAT_AGENT_MAX_STEPS_LIMIT = MAX_LLM_TURNS_LIMIT + MAX_TOOL_CALLS_LIMIT
# 出力開始前の一時的なプロバイダ障害を再試行する回数と待機時間
# Retry budget and backoff for transient provider failures before any output is emitted.
DEFAULT_LLM_STREAM_MAX_RETRIES = 2
LLM_STREAM_RETRY_BASE_DELAY_SECONDS = 0.5
LLM_STREAM_RETRY_MAX_DELAY_SECONDS = 8.0
# 停止要求が別ワーカーへ届いた場合に、所有ワーカーの応答を待つ上限と再確認間隔。
# Bounds for waiting on the owning worker after a stop request lands on another worker.
DEFAULT_REMOTE_CANCEL_TIMEOUT_SECONDS = 5.0
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


def _decode_redis_text(raw: Any) -> str | None:
    """Return Redis payloads as text regardless of the client's decode settings."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8")
        except Exception:
            return None
    return None


def _latest_user_message_text(messages: list[dict[str, Any]]) -> str:
    """Return the latest user prompt for request-aware UI recovery."""
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else str(content or "")
    return ""


# ストリーミング中の応答テキストから Artifact 等の UI パーツ情報をパースして更新用ペイロードを組み立てる
# Parse UI parts like Artifacts from streaming response text and build the update payload
def _build_streaming_parts_update(raw_text: str) -> dict[str, Any] | None:
    if "chatcore-artifact" not in raw_text and "chatcore-buttons" not in raw_text:
        return None

    normalized_response = normalize_response_with_artifacts(raw_text, allow_fallback=False)
    if normalized_response.validation_errors or not normalized_response.parts:
        return None

    if not any(part.get("type") != "text" for part in normalized_response.parts):
        return None

    return {
        "response": normalized_response.text,
        "parts": normalized_response.parts,
    }


# 表示用の合計ステップ上限を取得する
# Retrieve the displayed total step budget.
def _get_chat_agent_max_steps() -> int:
    return AgentStepBudget.from_environment().max_steps


# 環境変数からLLMストリーミング接続の最大再試行回数を取得する
# Retrieve the maximum retry limit for the LLM stream from environment variables
def _get_llm_stream_max_retries() -> int:
    raw = os.environ.get("LLM_STREAM_MAX_RETRIES")
    if raw is None:
        return DEFAULT_LLM_STREAM_MAX_RETRIES
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LLM_STREAM_MAX_RETRIES
    return max(value, 0)


# LLMストリーミング再試行時の遅延時間を計算する（指数バックオフ）
# Calculate the delay duration for LLM stream retries (exponential backoff)
def _llm_stream_retry_delay(exc: BaseException, attempt: int) -> float:
    # サーバー指定 of retry_afterを優先し、なければ指数バックオフ（上限あり）を用いる
    # Prefer server-provided retry_after, otherwise use capped exponential backoff.
    retry_after = getattr(exc, "retry_after_seconds", None)
    if isinstance(retry_after, int) and retry_after > 0:
        return min(float(retry_after), LLM_STREAM_RETRY_MAX_DELAY_SECONDS)
    delay = LLM_STREAM_RETRY_BASE_DELAY_SECONDS * (2 ** attempt)
    return min(delay, LLM_STREAM_RETRY_MAX_DELAY_SECONDS)


# ストリームのチャンク文字列からツール呼び出し（JSON形式）を解析する
# Parse tool calls (JSON format) from a stream chunk string
def _parse_tool_calls_chunk(chunk: str) -> list[dict[str, Any]] | None:
    stripped = chunk.strip()
    if not stripped.startswith("[") or '"function"' not in stripped:
        return None
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


# 検索クエリ・日付フィルタ・検索言語を正規化したキーを生成する
# Generate a normalized key from the query, freshness filter, and search language
def _normalized_search_key(
    query: Any,
    freshness: Any = "",
    search_language: Any = "",
) -> tuple[str, str, str]:
    normalized_query = " ".join(str(query or "").split())
    normalized_freshness = str(freshness or "").strip()
    normalized_language = str(search_language or "").strip().casefold()
    return (normalized_query.casefold(), normalized_freshness, normalized_language)


# ツール呼び出しオブジェクトに必要なIDやデフォルト値などを設定して正規化する
# Normalize a tool call object by setting required IDs and default values
def _normalize_tool_call(tool_call: dict[str, Any], *, step: int, index: int) -> dict[str, Any]:
    normalized = dict(tool_call)
    function = dict(normalized.get("function") or {})
    normalized["function"] = function
    normalized["type"] = normalized.get("type") or "function"
    normalized["id"] = str(normalized.get("id") or f"call-{step}-{index}")
    function["name"] = str(function.get("name") or "")
    function["arguments"] = str(function.get("arguments") or "{}")
    return normalized


# ツール実行結果を表すメッセージオブジェクトを構築する
# Construct a message object representing the tool execution result
def _tool_result_message(tool_call: dict[str, Any], content: dict[str, Any] | str) -> dict[str, Any]:
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return {
        "role": "tool",
        "tool_call_id": tool_call.get("id"),
        "name": tool_call.get("function", {}).get("name", ""),
        "content": content,
    }


# ツールへ返却するWeb検索結果ペイロードを整形する
# Format the Web search result payload returned to the tool
def _web_search_result_tool_payload(
    result: WebSearchResult,
    *,
    cached: bool = False,
    max_chars: int = WEB_SEARCH_MAX_CONTEXT_CHARS,
) -> dict[str, Any]:
    max_chars = max(1, min(int(max_chars), WEB_SEARCH_MAX_CONTEXT_CHARS))
    sources: list[dict[str, Any]] = []
    for source in result.sources:
        item: dict[str, Any] = {
            "evidence_id": source.evidence_id,
            "url": source.url[:320],
            "title": source.title[:160],
            "hostname": source.hostname[:120],
            "age": source.age[:80],
            "snippets": [],
        }
        if source.link_depth:
            item["link_depth"] = source.link_depth
        if source.linked_from_url:
            item["linked_from_url"] = source.linked_from_url[:160]
        sources.append(item)

    payload: dict[str, Any] = {
        "status": "completed",
        "cached": cached,
        "query": result.query[:240],
        "searched_at": result.searched_at[:80],
        "source_count": len(result.sources),
        "sources": sources,
    }
    detailed_count = sum(
        1 for source in result.sources if source.snippets or source.page_text
    )
    base_length = len(json.dumps(payload, ensure_ascii=False))
    per_source_budget = max(
        0,
        (max_chars - base_length) // max(1, detailed_count) - 32,
    )
    for item, source in zip(sources, result.sources):
        remaining = per_source_budget
        if source.snippets and remaining > 0:
            snippet = source.snippets[0][: min(400, remaining)]
            item["snippets"] = [snippet]
            remaining -= len(snippet)
        if source.page_text and remaining > 0:
            item["page_text"] = source.page_text[:remaining]

    # JSON escaping adds a small amount of overhead. Trim details, never source IDs,
    # until the serialized tool result is within the same context budget.
    while len(json.dumps(payload, ensure_ascii=False)) > max_chars:
        overflow = len(json.dumps(payload, ensure_ascii=False)) - max_chars
        changed = False
        for item in reversed(sources):
            page_text = item.get("page_text")
            if isinstance(page_text, str) and page_text:
                item["page_text"] = page_text[: max(0, len(page_text) - overflow - 8)]
                changed = True
                break
            snippets = item.get("snippets")
            if isinstance(snippets, list) and snippets:
                item["snippets"] = []
                changed = True
                break
        if not changed:
            break
    # Adversarial metadata can expand substantially when JSON-escaped. Remove optional
    # fields in a stable order while preserving every server-issued evidence ID.
    optional_fields = (
        "linked_from_url",
        "age",
        "url",
        "hostname",
        "title",
        "link_depth",
        "snippets",
    )
    for field in optional_fields:
        if len(json.dumps(payload, ensure_ascii=False)) <= max_chars:
            break
        for item in reversed(sources):
            item.pop(field, None)
            if len(json.dumps(payload, ensure_ascii=False)) <= max_chars:
                break
    if len(json.dumps(payload, ensure_ascii=False)) > max_chars:
        payload["query"] = ""
        payload["searched_at"] = ""

    # 予算を使い切ると本文もスニペットも残らない。それを "completed" のまま返すと、
    # モデルは「検索は成功したが何も書いていない」根拠を受け取り、出典IDだけを引用しかねない。
    # 状態を明示し、追加検索ではなく既存の根拠で答えるよう伝える。
    # An exhausted budget leaves neither page text nor snippets. Returning that as
    # "completed" hands the model evidence that succeeded yet says nothing, and invites it to
    # cite bare source IDs. Say so explicitly and steer it back to the evidence it already has.
    if detailed_count and not any(
        item.get("page_text") or item.get("snippets") for item in sources
    ):
        payload["status"] = "evidence_truncated"
        payload["message"] = (
            "This answer's evidence budget is exhausted, so the source text was omitted. "
            "Answer from the evidence already gathered and do not request another search."
        )
        # The status explanation is added after optional metadata has been trimmed. Keep the
        # explanation within the requested budget whenever the required evidence IDs leave room;
        # for an impossibly tiny budget, preserving IDs and the explicit status is safer than
        # silently returning a misleading successful result.
        while len(json.dumps(payload, ensure_ascii=False)) > max_chars:
            message = payload.get("message")
            if not isinstance(message, str) or not message:
                break
            overflow = len(json.dumps(payload, ensure_ascii=False)) - max_chars
            if len(message) <= overflow + 8:
                break
            payload["message"] = f"{message[: len(message) - overflow - 8].rstrip()}..."
    return payload


def _budgeted_web_search_result_tool_payload(
    result: WebSearchResult,
    budget: WebEvidenceContextBudget,
    *,
    cached: bool = False,
    telemetry: ChatGenerationTelemetry | None = None,
) -> dict[str, Any]:
    limit = budget.message_limit(WEB_SEARCH_TOOL_CONTEXT_MAX_CHARS)
    payload = _web_search_result_tool_payload(
        result,
        cached=cached,
        max_chars=limit,
    )
    budget.consume(len(json.dumps(payload, ensure_ascii=False)))
    if telemetry is not None:
        truncated = payload.get("status") == "evidence_truncated"
        telemetry.record_evidence_payload(
            empty=truncated and not payload.get("query"),
            truncated=truncated,
        )
    return payload


# 同一の部屋・ユーザーで既に生成ジョブが実行中である場合に投げられる例外クラス
# Exception class raised when a generation job is already running for the same room/user
class ChatGenerationAlreadyRunningError(RuntimeError):
    pass


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


# 個別のチャット応答生成のバックグラウンドタスクおよびイベントを管理するクラス
# Class that manages the background task and events for a single chat response generation
class ChatGenerationJob:
    # ジョブを初期化する
    # Initialize the job
    def __init__(
        self,
        *,
        conversation_messages: list[dict[str, Any]],
        model: str,
        persist_response: Callable[..., dict[str, Any] | None],
        on_finished: Callable[[], None] | None = None,
        on_event: Callable[[ChatGenerationEvent], None] | None = None,
        on_error: Callable[[], None] | None = None,
        prior_web_search_results: list[WebSearchResult] | None = None,
        is_cancel_requested: Callable[[], bool] | None = None,
        personal_knowledge_search: Callable[[str], dict[str, Any]] | None = None,
        shared_prompt_search: Callable[[str], dict[str, Any]] | None = None,
        selected_reference_trace: list[SelectedReferenceLookupTrace] | None = None,
        ui_mode: GenerativeUiMode | str | None = None,
    ) -> None:
        self._conversation_messages = [dict(message) for message in conversation_messages]
        self._model = model
        self._ui_mode = ui_mode
        self._prior_web_search_results = list(prior_web_search_results or [])
        # メモ/マイコンテキスト検索。ユーザーIDに束ねた呼び出し側のクロージャを受け取るので、
        # ジョブ自身はセッションもDBも知らないままでいられる。None のときは機能そのものが無効。
        # Memo / My Context lookup. The caller passes a closure already bound to a user id, so the
        # job stays free of session and database concerns. None means the feature is off.
        self._personal_knowledge_search = personal_knowledge_search
        # 公開プロンプト検索。公開データなので未ログインでも渡せる。None のときは無効。
        # Public prompt lookup. The data is public, so guests can have it too; None means off.
        self._shared_prompt_search = shared_prompt_search
        self._selected_reference_trace = list(selected_reference_trace or [])
        self._persist_response = persist_response
        self._on_finished = on_finished
        self._on_finished_called = False
        self._on_event = on_event
        self._on_error = on_error
        # 他プロセスからの停止要求を拾うためのフック。Pub/Sub 通知を取りこぼしても
        # このポーリングで最終的に停止できるようにしておく。
        # Hook for stop requests raised by another process. Polling here guarantees the job
        # still stops even if the pub/sub notification is missed.
        self._is_cancel_requested = is_cancel_requested
        self._next_cancel_check_at = 0.0
        self._events: list[ChatGenerationEvent] = []
        self._next_sequence_id = 1
        self._condition = threading.Condition()
        self._future: Future[None] | None = None
        self._cancelled: bool = False
        # 生成途中で停止された場合でも保存できるよう、出力済みチャンクを保持する。
        # Keep emitted chunks so a mid-stream stop can still persist the partial reply.
        self._chunks: list[str] = []
        # ツール呼び出しの有無が確定するまでの一時チャンク。キャンセル時だけ部分応答として使う。
        # Buffer the current model step until tool-call presence is known; use it as a partial
        # response only when the user cancels generation.
        self._pending_stream_chunks: list[str] = []
        # 調査の締めステップなど、ユーザー向け本文にならない一時バッファであることの印。
        # Marks a pending buffer that is internal-only and must never be saved as the answer.
        self._pending_stream_is_internal = False
        # 継続中に全文を書き直しているかどうか。停止時は全文をそのまま足さず接合する。
        # Whether a continuation is rewriting the full answer; cancellation must splice it.
        self._pending_stream_is_rewrite = False
        # Search-image selections are made as soon as search results arrive so a
        # cancellation can still persist images that were already revealed.
        self._selected_web_search_images: list[dict[str, str]] = []
        self._finalize_lock = threading.Lock()
        self._response_persisted = False
        # 1ターン分の生成テレメトリ。長いステップのターンで「短い（不足生成）」と
        # 「切れた（打ち切り）」を運用ログから切り分けるために集計する。
        # Per-turn telemetry so operations can separate under-generation from truncation on
        # long, many-step turns straight from the structured logs.
        self._telemetry = ChatGenerationTelemetry(model=model)
        self.response = ""
        self.error_message: str | None = None
        self.started_at = time.monotonic()
        self.finished_at: float | None = None
        self.is_done = False

    # 生成された最終応答とUIパーツ情報を永続化（データベース等へ保存）する
    # Persist the final generated response and UI parts info (save to database, etc.)
    def _persist_generated_response(
        self,
        response: str,
        message_parts: list[dict[str, Any]] | None,
        web_search_context: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        try:
            signature = inspect.signature(self._persist_response)
            parameters = signature.parameters
            has_var_keyword = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            accepts_message_parts = "message_parts" in parameters or has_var_keyword
            accepts_web_search_context = (
                "web_search_context" in parameters or has_var_keyword
            )
        except (TypeError, ValueError):
            accepts_message_parts = False
            accepts_web_search_context = False

        kwargs: dict[str, Any] = {}
        if accepts_message_parts:
            kwargs["message_parts"] = message_parts
        if accepts_web_search_context and web_search_context:
            kwargs["web_search_context"] = web_search_context
        return self._persist_response(response, **kwargs)

    # 応答の永続化を一度だけ実行する（完了とキャンセルの二重保存を防ぐ）
    # Persist the response at most once (avoid double-saving on completion vs. cancel)
    def _persist_once(
        self,
        response: str,
        message_parts: list[dict[str, Any]] | None,
        web_search_context: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        with self._finalize_lock:
            if self._response_persisted:
                return None
            self._response_persisted = True
        return self._persist_generated_response(
            response,
            message_parts,
            web_search_context=web_search_context,
        )

    # ジョブの非同期処理をスレッドプール上で開始する
    # Start the job's asynchronous processing in the thread pool
    def start(self) -> None:
        if self._future is not None:
            return
        self._future = submit_background_task(self._run)

    # ジョブの実行をキャンセルし、生成途中のテキストを保存して abortedイベントを発行する
    # Cancel the job, persist any partial text, and publish an aborted event
    def cancel(self) -> None:
        # 生成をキャンセルし、aborted イベントを発行して完了とする。
        # ここまでに生成されたテキストがあれば保存し、停止後も残るようにする。
        # Cancel generation and mark it complete with an aborted event.
        # If any text was produced before the stop, persist it so it is not lost.
        if self.is_done:
            return
        self._cancelled = True

        if self._pending_stream_chunks and not self._pending_stream_is_internal:
            # 調査ステップの途中で停止した場合、内部メモが本文として残らないよう取り除く。
            # A stop during a research step must not leave internal notes in the saved body.
            pending_text = strip_internal_notes("".join(self._pending_stream_chunks))
            existing_text = "".join(self._chunks)
            # 競合で書き直しフラグを読む前に停止しても、既存本文の末尾を先に錨として
            # 探す。通常の継続の境界重複にも同じ処理が効き、短い本文だけは従来の窓で補う。
            # Use the existing tail as an anchor even if cancellation races the rewrite-mode
            # flag. The same splice handles normal boundary overlap; the window covers short text.
            should_splice = self._pending_stream_is_rewrite or looks_like_restarted_answer(
                existing_text,
                pending_text,
            )
            if should_splice:
                spliced_pending = splice_restarted_answer(existing_text, pending_text)
                if spliced_pending is not None:
                    pending_text = spliced_pending
                else:
                    # 書き直しを接合できない場合は本文を丸ごと捨て、二重化を優先して防ぐ。
                    # If a rewrite cannot be spliced, drop it rather than duplicating the answer.
                    pending_text = ""
            else:
                pending_text = strip_continuation_overlap(existing_text, pending_text)
            self._pending_stream_chunks = []
            self._pending_stream_is_rewrite = False
            if pending_text:
                self._chunks.append(pending_text)
                self._publish("chunk", {"text": pending_text})
        partial_text = "".join(self._chunks)
        if not partial_text.strip():
            # まだ本文が無い場合は空応答を保存せず、中断のみ通知する。
            # No body yet: skip persisting an empty reply and only signal the abort.
            self._publish("aborted", {}, done=True)
            return

        normalized_response = normalize_response_with_artifacts(
            partial_text,
            recover_truncated=True,
            ui_mode=self._ui_mode,
        )
        bot_reply = normalized_response.text
        message_parts = normalized_response.parts
        if self._selected_web_search_images:
            message_parts = append_web_search_image_parts(
                message_parts,
                self._selected_web_search_images,
                fallback_text=bot_reply,
            )
            if message_parts:
                message_parts = normalize_message_parts_for_display(message_parts) or None
        self.response = bot_reply

        persist_metadata: dict[str, Any] | None = None
        try:
            persist_metadata = self._persist_once(bot_reply, message_parts)
        except Exception:
            logger.exception("Failed to persist partial chat response on cancel.")

        aborted_payload: dict[str, Any] = {"response": bot_reply, "partial": True}
        if message_parts:
            aborted_payload["parts"] = message_parts
        if isinstance(persist_metadata, dict):
            aborted_payload.update(persist_metadata)
        self._publish("aborted", aborted_payload, done=True)

    # 自プロセス・他プロセスのいずれかから停止が要求されたかを判定する
    # Report whether a stop was requested from this process or from another one
    def _should_stop(self) -> bool:
        if self._cancelled:
            return True
        if self._is_cancel_requested is None:
            return False

        # 停止要求の確認は外部ストア参照になるため、一定間隔に間引く。
        # Checking the stop request hits an external store, so throttle it.
        now = time.monotonic()
        if now < self._next_cancel_check_at:
            return False
        self._next_cancel_check_at = now + REMOTE_CANCEL_CHECK_INTERVAL_SECONDS

        try:
            requested = bool(self._is_cancel_requested())
        except Exception:
            logger.exception("Failed to check remote chat generation cancel request.")
            return False
        if requested:
            self.cancel()
        return self._cancelled

    # ジョブスレッドの完了を待機する
    # Wait for the job thread to complete
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

    # 生成中のイベントを発生順にストリーミング（イテレート）する
    # Stream (iterate) generation events in chronological order
    def iter_events(
        self,
        *,
        after_sequence_id: int = 0,
        heartbeat_seconds: float = DEFAULT_SSE_HEARTBEAT_SECONDS,
    ) -> Iterator[ChatGenerationEvent | None]:
        cursor = 0
        heartbeat_interval = max(float(heartbeat_seconds), 0.0)
        next_heartbeat_at = time.monotonic() + heartbeat_interval
        while True:
            heartbeat_due = False
            with self._condition:
                while (
                    cursor < len(self._events)
                    and self._events[cursor].sequence_id <= after_sequence_id
                ):
                    cursor += 1

                while cursor >= len(self._events) and not self.is_done:
                    wait_timeout = 0.5
                    if heartbeat_interval:
                        wait_timeout = min(
                            wait_timeout,
                            max(next_heartbeat_at - time.monotonic(), 0.0),
                        )
                    self._condition.wait(timeout=wait_timeout)
                    if (
                        heartbeat_interval
                        and cursor >= len(self._events)
                        and not self.is_done
                        and time.monotonic() >= next_heartbeat_at
                    ):
                        heartbeat_due = True
                        next_heartbeat_at = time.monotonic() + heartbeat_interval
                        break

                if heartbeat_due:
                    event = None
                elif cursor < len(self._events):
                    event = self._events[cursor]
                    cursor += 1
                    next_heartbeat_at = time.monotonic() + heartbeat_interval
                elif self.is_done:
                    break
                else:
                    continue

            yield event

    # 新しいイベントを発行し、待機スレッドおよび分散イベントチャネルに通知する
    # Publish a new event, notifying waiting threads and distributed event channels
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

    # ジョブの状態を「完了」にマークする
    # Mark the job status as done
    def _mark_done(self) -> Callable[[], None] | None:
        if self.is_done:
            return None
        self.is_done = True
        self.finished_at = time.monotonic()
        if self._on_finished_called or self._on_finished is None:
            return None
        self._on_finished_called = True
        return self._on_finished

    # エラー情報を設定し、errorイベントを発行してジョブを終了する
    # Set error details, publish an error event, and terminate the job
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

    # キャンセルを監視しながら、指定された秒数待機（スリープ）する
    # Sleep for a specified duration while monitoring for cancellation
    def _sleep_with_cancel(self, delay: float) -> bool:
        deadline = time.monotonic() + max(delay, 0.0)
        while time.monotonic() < deadline:
            if self._cancelled:
                return True
            time.sleep(min(0.1, max(deadline - time.monotonic(), 0.0)))
        return self._cancelled

    # 一時的な障害時に再試行しつつ、LLMからの応答ストリームのチャンクをイテレートする
    # Iterate LLM response stream chunks, retrying on transient provider failures
    def _iter_llm_stream_with_retry(
        self,
        current_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        generation_phase: str = "default",
        discard_partial_on_retry: bool = False,
        tolerate_output_limit: bool = False,
    ) -> Iterator[str]:
        # 出力開始前の一時的なプロバイダ障害のみ再試行し、内部エラー表示を抑制する。
        # 一度でもチャンクを送出した後は重複出力を避けるため再試行しない。
        # Retry transient provider failures only before any chunk is emitted, so brief
        # upstream blips do not surface as an internal error. Never retry once a chunk has
        # been emitted, to avoid duplicated or garbled output.
        max_retries = _get_llm_stream_max_retries()
        attempt = 0
        while True:
            emitted = False
            attempt_chunks: list[str] = []
            try:
                for chunk in get_llm_response_stream(
                    current_messages,
                    self._model,
                    tools=tools,
                    generation_phase=generation_phase,
                ):
                    if self._should_stop():
                        return
                    emitted = True
                    if discard_partial_on_retry:
                        attempt_chunks.append(chunk)
                        self._pending_stream_chunks[:] = attempt_chunks
                    else:
                        yield chunk
                if discard_partial_on_retry:
                    self._pending_stream_chunks.clear()
                    yield from attempt_chunks
                return
            except LlmOutputLimitError as exc:
                # 調査ステップが出力上限に当たっただけでターン全体を落とさない。プロバイダは
                # 例外の前に収集済みのツール呼び出しを流すので、それを使って調査を続ける。
                # A research step hitting its output cap must not fail the whole turn. The
                # provider emits the tool calls it collected before raising, so use them and
                # let the loop carry on.
                if not tolerate_output_limit:
                    raise
                logger.warning(
                    "Tolerating an output-limited stream and using its partial result "
                    "(model=%s, phase=%s, reason=%s).",
                    self._model,
                    generation_phase,
                    getattr(exc, "reason", exc.__class__.__name__),
                )
                self._telemetry.research_output_limit_recoveries += 1
                if discard_partial_on_retry:
                    buffered = list(attempt_chunks)
                    self._pending_stream_chunks.clear()
                    yield from buffered
                return
            except LlmRetryableProviderError as exc:
                if (
                    (emitted and not discard_partial_on_retry)
                    or isinstance(exc, LlmRateLimitError)
                    or attempt >= max_retries
                    or self._cancelled
                ):
                    raise
                if discard_partial_on_retry:
                    self._pending_stream_chunks.clear()
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

    # バックグラウンドスレッドで実行されるチャット応答生成のメインループ
    # The main loop for chat response generation executed in the background thread
    # 検索系ツールの呼び出しを1件実行する。ステップ会計は共有の予算オブジェクトが持つ。
    # メモ検索と共有プロンプト検索は進行管理が同じなので、1つの実行部を共有する。
    # Execute one lookup tool call. Step accounting lives in the shared budget object. The
    # memo and shared prompt tools share this runner because their handling is identical.
    def _run_lookup_tool_call(
        self,
        tool_call: dict[str, Any],
        *,
        tool_name: str,
        search: Callable[[str], dict[str, Any]] | None,
        event_prefix: str,
        result_counts: tuple[str, ...],
        failure_log_message: str,
        failure_tool_message: str,
        current_messages: list[dict[str, Any]],
        budget: AgentStepBudget,
        trace_steps: list[TraceStep] | None = None,
    ) -> None:
        if search is None:
            current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "unsupported_tool",
                        "message": f"Unsupported tool: {tool_name}",
                    },
                )
            )
            return

        args_raw = tool_call.get("function", {}).get("arguments", "{}")
        try:
            args = json.loads(args_raw)
        except Exception:
            args = {}
        if not isinstance(args, dict):
            args = {}

        query = str(args.get("query") or "").strip()
        if not query:
            current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "invalid_arguments",
                        "message": "Search query is empty.",
                    },
                )
            )
            return

        if budget.tool_calls_exhausted:
            current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "step_limit_reached",
                        "message": (
                            "The lookup step limit has been reached. "
                            "Answer using the information already available."
                        ),
                    },
                )
            )
            return

        step = budget.start_tool_call()
        self._telemetry.tool_calls = budget.tool_calls
        self._telemetry.lookup_call_count += 1
        self._publish(
            f"{event_prefix}_started",
            {"query": query, "step": step, "max_steps": budget.max_steps},
        )
        try:
            payload = search(query)
            if inspect.isawaitable(payload):
                # The generation loop is intentionally a synchronous worker because the LLM
                # stream is blocking. Native-async repository callbacks are bridged only at
                # this worker boundary; request-path database access never uses run_blocking.
                payload = asyncio.run(payload)  # type: ignore[arg-type]
            if not isinstance(payload, dict):
                raise TypeError("selected reference lookup returned a non-object payload")
        except Exception:
            logger.exception(failure_log_message)
            self._publish(
                f"{event_prefix}_failed",
                {"query": query, "step": step, "max_steps": budget.max_steps},
            )
            current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "failed",
                        "message": failure_tool_message,
                    },
                )
            )
            if trace_steps is not None:
                trace_steps.append(
                    selected_reference_step(
                        (
                            PERSONAL_KNOWLEDGE_SOURCE
                            if event_prefix == "personal_knowledge_search"
                            else SHARED_PROMPT_SOURCE
                        ),
                        {"status": "failed"},
                        query=query,
                    )
                )
            return

        # 参照元が「検索できなかった」と返した場合も障害として扱う。0件として通すと、
        # UI もモデルも「該当なし」と伝えてしまう。
        # A source reporting that it could not search is a failure too. Passing it through as a
        # zero-hit result would make both the UI and the model claim that nothing matched.
        status = str(payload.get("status") or "")
        if status == "failed":
            logger.warning("%s (status=failed)", failure_log_message)
            self._publish(
                f"{event_prefix}_failed",
                {"query": query, "step": step, "max_steps": budget.max_steps},
            )
            current_messages.append(_tool_result_message(tool_call, payload))
            if trace_steps is not None:
                trace_steps.append(
                    selected_reference_step(
                        (
                            PERSONAL_KNOWLEDGE_SOURCE
                            if event_prefix == "personal_knowledge_search"
                            else SHARED_PROMPT_SOURCE
                        ),
                        payload,
                        query=query,
                    )
                )
            return

        self._publish(
            f"{event_prefix}_completed",
            {
                "query": query,
                "status": status,
                **{key: int(payload.get(key) or 0) for key in result_counts},
                "step": step,
                "max_steps": budget.max_steps,
            },
        )
        current_messages.append(_tool_result_message(tool_call, payload))
        # 事前検索と同じクエリは既にトレースへ記録済みなので、重複行を追加しない。
        # A query satisfied by the prefetch is already present in the trace.
        if trace_steps is not None and status != "already_searched":
            trace_steps.append(
                selected_reference_step(
                    (
                        PERSONAL_KNOWLEDGE_SOURCE
                        if event_prefix == "personal_knowledge_search"
                        else SHARED_PROMPT_SOURCE
                    ),
                    payload,
                    query=query,
                )
            )
        return

    def _run(self) -> None:
        # キャンセル時に保存できるよう、インスタンス側のチャンクリストへ蓄積する。
        # Accumulate into the instance chunk list so a cancel can persist the partial text.
        chunks = self._chunks
        final_answer_incomplete: BaseException | None = None
        continuation_count = 0
        last_streaming_parts_signature: str | None = None
        web_search_results: list[WebSearchResult] = []
        web_search_results_by_key: dict[tuple[str, str, str], WebSearchResult] = {}
        web_search_trace_steps: list[TraceStep] = selected_reference_steps(
            self._selected_reference_trace
        )
        streaming_citation_buffer = ""
        current_messages = [dict(m) for m in self._conversation_messages]
        # 過去ターンの検索結果を参照用コンテキストとして再注入する
        # Re-inject prior-turn search results as a reference context.
        current_messages = inject_prior_web_search_context(
            current_messages, self._prior_web_search_results
        )
        suppress_next_generation_started = False
        budget = AgentStepBudget.from_environment()
        telemetry = self._telemetry
        page_fetch_budget = create_web_page_fetch_budget()
        # 根拠の予算は許可されたツール実行回数から算出する。予算が回数に足りないと、
        # 後半の検索が「中身ゼロで成功した検索結果」に化けてモデルを誤誘導する。
        # Size the evidence budget from the permitted tool calls: a budget that cannot cover
        # them turns later searches into "successful" results with no content at all.
        evidence_context_budget = create_web_evidence_context_budget(budget.max_tool_calls)
        telemetry.evidence_budget_max_chars = evidence_context_budget.max_chars
        coverage_requirements: tuple[str, ...] = ()
        latest_user_message = _latest_user_message_text(self._conversation_messages)
        selected_web_search_images = self._selected_web_search_images
        revealed_image_indices: list[int] = []
        revealed_image_offsets: list[int] = []
        streamed_display_text = ""

        def collect_web_search_image_selections(result: WebSearchResult | None) -> None:
            """Select images as soon as a search result becomes available."""
            if result is None or len(selected_web_search_images) >= MAX_WEB_SEARCH_IMAGES_PER_REPLY:
                return
            try:
                selections = choose_web_search_images(
                    latest_user_message,
                    result,
                    model=self._model,
                    answer_text=streamed_display_text,
                )
            except Exception:
                logger.warning(
                    "Web search image selection failed during streaming; continuing without an image.",
                    exc_info=True,
                )
                return
            existing_urls = {
                str(selection.get("url") or "")
                for selection in selected_web_search_images
                if isinstance(selection, dict)
            }
            for selection in selections:
                if not isinstance(selection, dict):
                    continue
                image_url = str(selection.get("url") or "")
                if not image_url or image_url in existing_urls:
                    continue
                selected_web_search_images.append(selection)
                existing_urls.add(image_url)
                if len(selected_web_search_images) >= MAX_WEB_SEARCH_IMAGES_PER_REPLY:
                    break
            # A model-requested search can finish after prose has already streamed.
            # Reconcile selected images against that existing text immediately.
            publish_stream_text_with_images("")

        def publish_stream_chunk(text: str) -> None:
            nonlocal streamed_display_text
            if not text:
                return
            self._publish("chunk", {"text": text})
            streamed_display_text += text

        def publish_stream_text_with_images(text: str) -> None:
            """Emit text and reveal images at stable offsets, including past text."""
            pending_text = text
            while True:
                raw_parts_update = _build_streaming_parts_update("".join(chunks))
                if raw_parts_update is not None:
                    if pending_text:
                        publish_stream_chunk(pending_text)
                    return

                image_parts = build_web_search_image_parts(selected_web_search_images)
                next_image = find_next_streaming_image_insertion(
                    f"{streamed_display_text}{pending_text}",
                    image_parts,
                    revealed_indices=set(revealed_image_indices),
                    after_offset=revealed_image_offsets[-1] if revealed_image_offsets else 0,
                )
                if next_image is None:
                    if pending_text:
                        publish_stream_chunk(pending_text)
                    return

                insertion_offset, image_index = next_image
                current_text_length = len(streamed_display_text)
                relative_offset = insertion_offset - current_text_length
                if relative_offset < 0:
                    relative_offset = 0
                if relative_offset > len(pending_text):
                    if pending_text:
                        publish_stream_chunk(pending_text)
                    return

                if relative_offset:
                    publish_stream_chunk(pending_text[:relative_offset])
                revealed_image_indices.append(image_index)
                revealed_image_offsets.append(insertion_offset)
                visible_image_parts = [
                    image_parts[index] for index in revealed_image_indices
                ]
                visible_parts = build_web_search_image_parts_at_offsets(
                    streamed_display_text,
                    visible_image_parts,
                    revealed_image_offsets,
                    keep_empty_tail=True,
                )
                self._publish(
                    "response_parts_updated",
                    {
                        "response": streamed_display_text,
                        "parts": visible_parts,
                    },
                )
                pending_text = pending_text[relative_offset:]

        def publish_completed_answer_step(step_chunks: list[str]) -> None:
            """Publish a model step only after confirming it requested no tools."""
            nonlocal last_streaming_parts_signature, streaming_citation_buffer
            for raw_chunk in step_chunks:
                chunk = raw_chunk
                if not chunks:
                    combined_web_search_result = combine_web_search_results(web_search_results)
                    if web_search_trace_steps or combined_web_search_result is not None:
                        web_search_trace_steps.append(answer_step(web_search_results))
                    trace_block = build_web_search_trace_markdown(
                        combined_web_search_result,
                        steps=web_search_trace_steps,
                    )
                    if trace_block:
                        chunk = f"{trace_block}\n\n{chunk}"

                chunks.append(chunk)
                streaming_evidence = combine_web_search_results(
                    [*web_search_results, *self._prior_web_search_results]
                )
                # モデルが真似て書いたチップHTMLは、検索根拠の有無にかかわらず
                # 表示前に取り除く。正規のチップはこの後の解決処理だけが描画する。
                # Chip markup echoed by the model is removed before display whether or
                # not this turn has evidence; only the resolution below renders chips.
                complete_stream_text, streaming_citation_buffer = (
                    split_web_search_citation_stream_text(
                        f"{streaming_citation_buffer}{chunk}"
                    )
                )
                complete_stream_text = strip_web_search_citation_html(
                    complete_stream_text
                )
                if streaming_evidence is None:
                    stream_text = complete_stream_text
                else:
                    stream_text = resolve_web_search_citations(
                        complete_stream_text,
                        streaming_evidence,
                    ).text
                if stream_text:
                    publish_stream_text_with_images(stream_text)
                streaming_parts_update = _build_streaming_parts_update("".join(chunks))
                if streaming_parts_update is not None:
                    if streaming_evidence is not None:
                        parts_resolution = resolve_web_search_citations(
                            streaming_parts_update["response"],
                            streaming_evidence,
                        )
                        resolved_parts_text = parts_resolution.text
                        streaming_parts_update = {
                            **streaming_parts_update,
                            "response": resolved_parts_text,
                            "parts": [
                                (
                                    {**part, "text": resolved_parts_text}
                                    if part.get("type") == "text"
                                    else part
                                )
                                for part in streaming_parts_update["parts"]
                            ],
                        }
                    streaming_parts_signature = json.dumps(
                        streaming_parts_update,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    if streaming_parts_signature != last_streaming_parts_signature:
                        last_streaming_parts_signature = streaming_parts_signature
                        self._publish("response_parts_updated", streaming_parts_update)

        def publish_answer_chunk(chunk: str) -> None:
            """Publish one chunk from a tool-free answer stream immediately."""
            if chunk:
                publish_completed_answer_step([chunk])

        def adopt_continuation_buffer(buffer: list[str]) -> None:
            # 継続パスの未配信バッファをジョブ側へ預ける。停止・切断でも保存経路に載る。
            # Hand the continuation pass's undelivered buffer to the job so a stop or a
            # disconnect still routes it through the persistence path.
            self._pending_stream_chunks = buffer
            self._pending_stream_is_rewrite = False

        def set_continuation_buffer_mode(is_rewrite: bool) -> None:
            # 継続パスが全文の書き直しへ切り替わったことを停止経路へ伝える。
            # Tell the cancellation path when a continuation has switched to a full rewrite.
            self._pending_stream_is_rewrite = is_rewrite

        def stream_final_answer(
            answer_messages: list[dict[str, Any]],
            *,
            deep_reasoning: bool = False,
        ) -> BaseException | None:
            nonlocal continuation_count
            try:
                result = stream_final_answer_with_recovery(
                    answer_messages,
                    model=self._model,
                    iter_stream=lambda messages, phase: self._iter_llm_stream_with_retry(
                        messages,
                        tools=None,
                        generation_phase=phase,
                    ),
                    publish_chunk=publish_answer_chunk,
                    publish_event=self._publish,
                    should_stop=self._should_stop,
                    adopt_buffer=adopt_continuation_buffer,
                    adopt_buffer_mode=set_continuation_buffer_mode,
                    answer_phase="final_answer_deep" if deep_reasoning else "final_answer",
                    continuation_phase=(
                        "continuation_deep" if deep_reasoning else "continuation"
                    ),
                )
            finally:
                # 通常完了・入力超過・キャンセルのどの経路でも、次の保存処理が古い共有
                # バッファや書き直しモードを誤って拾わないようにする。
                # Clear shared state on every exit so later persistence cannot adopt a stale
                # continuation buffer or rewrite mode.
                self._pending_stream_chunks = []
                self._pending_stream_is_rewrite = False
            continuation_count = result.continuation_count
            self._telemetry.continuation_count = result.continuation_count
            for reason in result.reasons:
                self._telemetry.record_continuation_reason(reason)
            self._telemetry.continuation_stalled = result.stalled
            self._telemetry.continuation_restart_trimmed = result.restart_trimmed
            if result.error is not None:
                self._telemetry.first_pass_finish_reason = getattr(
                    result.error, "reason", result.error.__class__.__name__
                )
            else:
                self._telemetry.first_pass_finish_reason = "stop"
            return result.error

        try:
            # ウェブ検索によるコンテキスト拡張の判定
            # Determine context augmentation using web search
            augmentation = maybe_augment_messages_with_web_search(
                current_messages,
                self._model,
                publish_event=self._publish,
                page_fetch_budget=page_fetch_budget,
                evidence_context_budget=evidence_context_budget,
            )
            current_messages = augmentation.messages
            if augmentation.result is not None:
                web_search_trace_steps.extend(
                    [
                        decision_step(augmentation.result),
                        search_step(augmentation.result),
                        *page_reading_steps(augmentation.result),
                        context_added_step(augmentation.result),
                    ]
                )
                web_search_results.append(augmentation.result)
                web_search_results_by_key[
                    _normalized_search_key(
                        augmentation.result.query,
                        augmentation.result.freshness,
                        augmentation.search_language,
                    )
                ] = augmentation.result
                collect_web_search_image_selections(augmentation.result)
                budget.start_tool_call()
                telemetry.web_search_count += 1
            elif augmentation.status in {"failed", "no_sources"}:
                budget.start_tool_call()
                web_search_trace_steps.append(search_failed_step())
            telemetry.tool_calls = budget.tool_calls
            # 依頼が満たすべき項目はプランナー呼び出しへ相乗りして取得済み。追加の
            # レイテンシなしで回答契約へ載せ、長い調査ターンのカバレッジ欠落を防ぐ。
            # The requirements the answer must satisfy ride along with the planner call, so
            # the contract gets them at no extra latency and long turns keep their coverage.
            coverage_requirements = augmentation.answer_requirements
            telemetry.coverage_requirement_count = len(coverage_requirements)
            suppress_next_generation_started = augmentation.status == "failed"
            research_phase_used = bool(self._selected_reference_trace) or bool(
                augmentation.result is not None
                or augmentation.status in {"failed", "no_sources"}
            )
            telemetry.research_phase_used = research_phase_used

            if self._should_stop():
                return

            web_search_tool = get_web_search_tool_definition()
            personal_knowledge_tool = (
                get_personal_knowledge_tool_definition()
                if self._personal_knowledge_search is not None
                else None
            )
            shared_prompt_tool = (
                get_shared_prompt_tool_definition()
                if self._shared_prompt_search is not None
                else None
            )

            # メモ検索はWeb検索の設定に依存しないので、どちらか一方だけでもツールを渡す。
            # Memo lookup does not depend on the web search settings, so either tool alone
            # is still offered to the model.
            configured_tools: list[dict[str, Any]] = []
            if is_web_search_enabled():
                configured_tools.append(web_search_tool)
            if personal_knowledge_tool is not None:
                configured_tools.append(personal_knowledge_tool)
            if shared_prompt_tool is not None:
                configured_tools.append(shared_prompt_tool)

            # 生成ループ（エージェントステップ）
            # Generation loop (agent steps)
            final_answer_required = False
            answer_stream_started = False
            research_summary: dict[str, Any] | None = None
            # 完了ノートが取れなかったときに最終回答へ引き継ぐ、モデル自身の下書き。
            # The model's own draft, carried to the answer pass when no note could be parsed.
            research_draft = ""
            # 各ステップが任意で書く「次の一手の根拠」。直近分だけを次のステップへ渡す。
            # The optional rationale each step may write for its next move; only the most
            # recent notes are carried into the following step.
            step_notes: list[str] = []
            while configured_tools:
                if self._should_stop():
                    return
                if budget.research_exhausted:
                    # 予算切れでツールを引き上げる。ここで打ち切ると完了ノートが無いまま
                    # 最終回答へ進むため、この後の締めステップで必ずノートを作る。
                    # The budget withdraws the tools here. Stopping now would enter the answer
                    # phase with no completion note, so a wrap-up step always writes one.
                    telemetry.tools_withdrawn_by_budget = True
                    final_answer_required = True
                    break

                # 調査ループ自身もツール結果を積み上げるため、最終回答だけでなく次の
                # ツール選択リクエストの前にも古い根拠を圧縮する。ここで入力超過すると
                # 締めステップや最終回答へ到達できず、長い調査ターン全体が失われる。
                # The research loop also accumulates tool results. Compact old evidence before
                # each next selection request, or an input overflow here would prevent both the
                # wrap-up and final-answer recovery from ever running.
                current_messages, _ = compact_tool_messages(
                    current_messages,
                    max_tokens=get_final_answer_input_token_budget(),
                )
                research_messages = (
                    build_research_loop_messages(
                        current_messages,
                        step_notes=step_notes,
                    )
                    if research_phase_used
                    else current_messages
                )
                research_messages, _ = compact_tool_messages(
                    research_messages,
                    max_tokens=get_final_answer_input_token_budget(),
                )
                llm_step = budget.start_llm_turn()
                telemetry.llm_turns = budget.llm_turns

                if not suppress_next_generation_started:
                    self._publish(
                        "response_generation_started",
                        {"step": llm_step, "max_steps": budget.max_steps},
                    )
                suppress_next_generation_started = False

                tool_calls_buffer: list[dict[str, Any]] = []
                step_chunks: list[str] = []
                self._pending_stream_chunks = step_chunks
                self._pending_stream_is_rewrite = False
                for chunk in self._iter_llm_stream_with_retry(
                    research_messages,
                    tools=configured_tools,
                    generation_phase="research",
                    discard_partial_on_retry=True,
                    tolerate_output_limit=True,
                ):
                    if self._should_stop():
                        return
                    if not chunk:
                        continue

                    parsed_tool_calls = _parse_tool_calls_chunk(chunk)
                    if parsed_tool_calls is not None:
                        tool_calls_buffer.extend(parsed_tool_calls)
                        continue
                    step_chunks.append(chunk)

                if self._should_stop():
                    return

                if not tool_calls_buffer:
                    self._pending_stream_chunks = []
                    self._pending_stream_is_rewrite = False
                    if research_phase_used:
                        # ツールなしは調査完了の合図。本文は破棄し、次のツール無効ストリームを
                        # ユーザー向けの最終回答として表示する。ノートを読めなかった場合だけ、
                        # 統合作業を失わないように下書きとして引き継ぐ。
                        # No tool call means the research loop is complete. Discard this draft and
                        # use the next tool-free stream for the user-facing final answer. Only when
                        # the note cannot be read is the draft carried on, so the synthesis the
                        # model already performed is not thrown away.
                        research_summary = parse_research_summary(step_chunks)
                        if research_summary is None:
                            research_draft = extract_research_draft(step_chunks)
                        final_answer_required = True
                    else:
                        # 検索を一度も使わない通常回答は、最初のストリームをそのまま表示する。
                        # For ordinary answers with no research phase, publish the first stream.
                        answer_stream_started = True
                        publish_completed_answer_step(step_chunks)
                    break

                # このステップは検索・参照のための中間生成なので、本文として表示・保存しない。
                # 任意のステップメモだけを取り出し、次のステップのsystemメッセージへ引き継ぐ。
                # This step is intermediate tool-use output; do not display or persist it as the answer.
                # Only the optional step note is kept, and it is carried into the next step's
                # system message.
                append_step_note(step_notes, parse_step_note(step_chunks))
                self._pending_stream_chunks = []
                self._pending_stream_is_rewrite = False
                research_phase_used = True
                telemetry.research_phase_used = True

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
                    # ツールごとの実行と結果の追加
                    # Execute each tool and append results
                    func_name = tc.get("function", {}).get("name")
                    if (
                        func_name == PERSONAL_KNOWLEDGE_TOOL_NAME
                        and self._personal_knowledge_search is not None
                    ):
                        self._run_lookup_tool_call(
                            tc,
                            tool_name=PERSONAL_KNOWLEDGE_TOOL_NAME,
                            search=self._personal_knowledge_search,
                            event_prefix="personal_knowledge_search",
                            result_counts=("memo_count", "context_fact_count"),
                            failure_log_message="Memo / context search via tool call failed.",
                            failure_tool_message="Memo and My Context search failed.",
                            current_messages=current_messages,
                            budget=budget,
                            trace_steps=web_search_trace_steps,
                        )
                        continue

                    if (
                        func_name == SHARED_PROMPT_TOOL_NAME
                        and self._shared_prompt_search is not None
                    ):
                        self._run_lookup_tool_call(
                            tc,
                            tool_name=SHARED_PROMPT_TOOL_NAME,
                            search=self._shared_prompt_search,
                            event_prefix="shared_prompt_search",
                            result_counts=("prompt_count",),
                            failure_log_message="Shared prompt search via tool call failed.",
                            failure_tool_message="Shared prompt search failed.",
                            current_messages=current_messages,
                            budget=budget,
                            trace_steps=web_search_trace_steps,
                        )
                        continue

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
                    search_language = args.get("search_language", "")
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

                    if budget.tool_calls_exhausted:
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

                    search_step_index = budget.start_tool_call()
                    telemetry.tool_calls = budget.tool_calls
                    query_text = str(query)
                    freshness_text = str(freshness or "")
                    search_key = _normalized_search_key(
                        query_text,
                        freshness_text,
                        search_language,
                    )
                    cached_result = web_search_results_by_key.get(search_key)

                    self._publish(
                        "web_search_started",
                        {
                            "query": query_text,
                            "reason": "Model-requested search",
                            "step": search_step_index,
                            "max_steps": budget.max_steps,
                            "cached": cached_result is not None,
                        },
                    )
                    if cached_result is not None:
                        web_search_trace_steps.extend(
                            [
                                search_step(cached_result, cached=True),
                                review_step(cached_result, reused=True),
                            ]
                        )
                        self._publish(
                            "web_search_completed",
                            {
                                "query": cached_result.query,
                                "source_count": len(cached_result.sources),
                                "step": search_step_index,
                                "max_steps": budget.max_steps,
                                "cached": True,
                            },
                        )
                        collect_web_search_image_selections(cached_result)
                        telemetry.cached_web_search_count += 1
                        current_messages.append(
                            _tool_result_message(
                                tc,
                                _budgeted_web_search_result_tool_payload(
                                    cached_result,
                                    evidence_context_budget,
                                    cached=True,
                                    telemetry=telemetry,
                                ),
                            )
                        )
                        continue

                    try:
                        result = search_brave_llm_context(
                            query_text,
                            freshness=freshness_text,
                            page_fetch_budget=page_fetch_budget,
                            language_hint=latest_user_message,
                            search_language=search_language,
                        )
                        web_search_results_by_key[search_key] = result
                        web_search_trace_steps.extend(
                            [
                                search_step(result, additional=bool(web_search_results)),
                                *page_reading_steps(result),
                                review_step(result),
                            ]
                        )
                        if result.has_sources:
                            web_search_results.append(result)
                        telemetry.web_search_count += 1
                        self._publish(
                            "web_search_completed",
                            {
                                "query": result.query,
                                "source_count": len(result.sources),
                                "step": search_step_index,
                                "max_steps": budget.max_steps,
                                "cached": False,
                            },
                        )
                        collect_web_search_image_selections(result)
                        current_messages.append(
                            _tool_result_message(
                                tc,
                                _budgeted_web_search_result_tool_payload(
                                    result,
                                    evidence_context_budget,
                                    telemetry=telemetry,
                                ),
                            )
                        )
                    except WebSearchQuotaExceeded as exc:
                        message = (
                            f"Web検索の月間上限（全体 {exc.limit} 回）に達しました。"
                            "検索なしで回答を続けます。"
                        )
                        web_search_trace_steps.append(
                            search_failed_step(
                                query_text,
                                reason="月間上限に達したため検索結果を取得できませんでした。",
                            )
                        )
                        suppress_next_generation_started = True
                        self._publish(
                            "web_search_failed",
                            {
                                "query": query_text,
                                "code": WEB_SEARCH_ERROR_QUOTA_EXCEEDED,
                                "message": message,
                                "retry_after_seconds": exc.retry_after_seconds,
                                "step": search_step_index,
                                "max_steps": budget.max_steps,
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
                            search_failed_step(
                                query_text,
                                reason="検索リクエストに失敗したため、取得済みの情報で回答を続けました。",
                            )
                        )
                        suppress_next_generation_started = True
                        self._publish(
                            "web_search_failed",
                            {
                                "query": query_text,
                                "code": WEB_SEARCH_ERROR_REQUEST_FAILED,
                                "message": "Web検索に失敗しました。検索なしで回答を続けます。",
                                "step": search_step_index,
                                "max_steps": budget.max_steps,
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

            if not answer_stream_started:
                # ツールループがステップ上限に達した場合も、取得済み情報で最終回答を生成する。
                # If the tool loop reaches its step limit, still generate a final answer from
                # the evidence collected so far.
                final_answer_required = True

            # ツール予算切れで打ち切ると、モデルは完了ノートを書く機会を得られない。
            # ノート不在のまま最終回答へ進むと、長い調査の要件が丸ごと落ちるため、
            # 締めのステップを1回だけ挟んでノートを必ず作る。
            # Being cut off at the tool budget denies the model the chance to write its
            # completion note. Entering the answer phase without one drops the requirements a
            # long research turn gathered, so run exactly one wrap-up step to produce it.
            if (
                telemetry.tools_withdrawn_by_budget
                and research_phase_used
                and final_answer_required
                and research_summary is None
                and not self._should_stop()
            ):
                self._publish(
                    "response_generation_started",
                    {
                        "step": budget.step + 1,
                        "max_steps": budget.max_steps,
                        "phase": "research_wrapup",
                    },
                )
                wrapup_chunks: list[str] = []
                # 締めステップの出力は完了ノートだけで、ユーザー向け本文ではない。
                # 停止時に本文として保存されないよう、内部バッファとして印を付ける。
                # The wrap-up emits only the completion note, never user-facing prose, so mark
                # the buffer internal to keep a stop from persisting it as the answer.
                self._pending_stream_chunks = wrapup_chunks
                self._pending_stream_is_internal = True
                self._pending_stream_is_rewrite = False
                try:
                    wrapup_messages, _ = compact_tool_messages(
                        build_research_wrapup_messages(current_messages),
                        max_tokens=get_final_answer_input_token_budget(),
                    )
                    for chunk in self._iter_llm_stream_with_retry(
                        wrapup_messages,
                        tools=None,
                        generation_phase="research_wrapup",
                        discard_partial_on_retry=True,
                        tolerate_output_limit=True,
                    ):
                        if self._should_stop():
                            return
                        if chunk:
                            wrapup_chunks.append(chunk)
                finally:
                    self._pending_stream_chunks = []
                    self._pending_stream_is_internal = False
                    self._pending_stream_is_rewrite = False
                telemetry.research_wrapup_used = True
                research_summary = parse_research_summary(wrapup_chunks)
                if research_summary is None and not research_draft:
                    research_draft = extract_research_draft(wrapup_chunks)

            if final_answer_required:
                self._pending_stream_chunks = []
                self._pending_stream_is_rewrite = False
                if not suppress_next_generation_started:
                    self._publish(
                        "response_generation_started",
                        {
                            "step": budget.step + 1,
                            "max_steps": budget.max_steps,
                            "phase": "final_answer",
                        },
                    )
                suppress_next_generation_started = False
                telemetry.research_summary_present = research_summary is not None
                telemetry.research_draft_forwarded = bool(research_draft)
                final_answer_messages = (
                    build_final_answer_messages(
                        current_messages,
                        research_summary=research_summary,
                        user_request=latest_user_message,
                        coverage_requirements=coverage_requirements,
                        research_draft=research_draft,
                    )
                    if research_phase_used
                    else current_messages
                )
                # 送る前に入力量を見積もり、超過しそうなら古い根拠から縮める。
                # 超過してから直すとターンごと「内部エラー」で失われる。
                # Estimate the request before sending and shrink the oldest evidence if it is
                # about to overflow: recovering after the fact loses the whole turn.
                final_answer_messages, compacted = compact_tool_messages(
                    final_answer_messages,
                    max_tokens=get_final_answer_input_token_budget(),
                )
                telemetry.final_answer_input_tokens = estimate_messages_tokens(
                    final_answer_messages
                )
                telemetry.final_answer_input_chars = estimate_messages_chars(
                    final_answer_messages
                )
                answer_stream_started = True
                try:
                    final_answer_incomplete = stream_final_answer(
                        final_answer_messages,
                        deep_reasoning=research_phase_used,
                    )
                except LlmInputLimitError:
                    # 見積もりが外れて実際に超過した場合の最後の砦。根拠を最小まで削って
                    # 一度だけやり直す。ここで諦めると回答が丸ごと失われる。
                    # Last resort when the estimate was wrong and the provider still refused:
                    # compact the evidence to the minimum and retry exactly once, because
                    # giving up here loses the answer entirely.
                    if chunks:
                        raise
                    logger.warning(
                        "Retrying the final answer after an input-limit rejection.",
                        extra={"model": self._model},
                    )
                    telemetry.input_limit_recoveries += 1
                    final_answer_messages, _ = compact_tool_messages(
                        final_answer_messages,
                        max_tokens=1,
                    )
                    telemetry.final_answer_input_tokens = estimate_messages_tokens(
                        final_answer_messages
                    )
                    telemetry.final_answer_input_chars = estimate_messages_chars(
                        final_answer_messages
                    )
                    final_answer_incomplete = stream_final_answer(
                        final_answer_messages,
                        deep_reasoning=research_phase_used,
                    )

            if streaming_citation_buffer:
                streaming_evidence = combine_web_search_results(
                    [*web_search_results, *self._prior_web_search_results]
                )
                buffered_text = strip_web_search_citation_html(
                    streaming_citation_buffer
                )
                if streaming_evidence is not None:
                    buffered_text = resolve_web_search_citations(
                        buffered_text,
                        streaming_evidence,
                    ).text
                if buffered_text:
                    publish_stream_text_with_images(buffered_text)

        # エラーハンドリング
        # Error handling
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
        except LlmInputLimitError:
            if self._cancelled:
                return
            logger.warning(
                "Chat generation stopped because the request exceeded the model context window.",
                extra=self._telemetry.as_log_extra(),
            )
            error_message = (
                "参照した情報が多すぎて、モデルが一度に扱える上限を超えました。"
                "質問を分けるか、参照を減らして再試行してください。"
            )
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": True},
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

        if self._should_stop():
            return

        bot_reply = "".join(chunks)
        if not chunks:
            combined_web_search_result = combine_web_search_results(web_search_results)
            if web_search_trace_steps or combined_web_search_result is not None:
                web_search_trace_steps.append(answer_step(web_search_results))
            trace_block = build_web_search_trace_markdown(
                combined_web_search_result,
                steps=web_search_trace_steps,
            )
            if trace_block:
                separator = "" if not bot_reply or trace_block.endswith("\n\n") else "\n\n"
                bot_reply = f"{trace_block}{separator}{bot_reply}"
        latest_user_message = _latest_user_message_text(self._conversation_messages)
        if final_answer_incomplete is not None:
            normalized_response = normalize_response_with_artifacts(
                bot_reply,
                recover_truncated=True,
                ui_mode=self._ui_mode,
            )
        else:
            normalized_response = normalize_response_with_artifact_retry(
                bot_reply,
                conversation_messages=current_messages,
                model=self._model,
                generate_response=get_llm_response,
                user_request=latest_user_message,
                ui_mode=self._ui_mode,
            )
        if normalized_response.validation_errors:
            logger.warning(
                "One or more generated UI artifacts failed validation and were omitted.",
                extra={"validation_errors": normalized_response.validation_errors},
            )
        bot_reply = normalized_response.text
        message_parts = normalized_response.parts

        # 現在ターンと過去ターンの検索根拠を照合し、モデルの引用markerを
        # 検証済みソースへのMarkdownリンクへ変換する。UIパーツがある場合も
        # 表示本文と保存本文が一致するよう、text partを同時に更新する。
        # Resolve model citation markers against current and prior evidence, then
        # keep the visible text part aligned with the persisted response.
        # 保存本文からもチップHTMLを取り除いてから、引用markerを解決する。
        # 順序を逆にすると、描画したばかりの正規チップまで消えてしまう。
        # Strip chip markup from the persisted body before resolving citation markers.
        # The reverse order would delete the chips this step just rendered.
        bot_reply = strip_web_search_citation_html(bot_reply)
        citation_evidence = combine_web_search_results(
            [*web_search_results, *self._prior_web_search_results]
        )
        resolved_citations = ()
        if citation_evidence is not None:
            citation_resolution = resolve_web_search_citations(
                bot_reply,
                citation_evidence,
            )
            if citation_resolution.invalid_markers:
                logger.warning(
                    "Removed invalid web search citation markers from generated response.",
                    extra={
                        "invalid_marker_count": len(citation_resolution.invalid_markers)
                    },
                )
            bot_reply = citation_resolution.text
            resolved_citations = citation_resolution.citations
            if message_parts:
                message_parts = [
                    (
                        {**part, "text": bot_reply}
                        if part.get("type") == "text"
                        else part
                    )
                    for part in message_parts
                ]

        # 画像は検索結果を取得した時点で選定済み。引用解決後は、選定LLMが返した
        # 配置計画を本文へ反映し、ストリーム中に表示した順序と保存内容を一致させる。
        # Image selection already happened when each search result arrived. After
        # citation resolution, realize the placement plan returned by the selector
        # so persisted history matches what the stream revealed.
        if selected_web_search_images:
            message_parts = append_web_search_image_parts(
                message_parts,
                selected_web_search_images,
                fallback_text=bot_reply,
            )

        # トレースを独立パーツへ分け、本文内の画像位置を維持したまま保存・配信する。
        # Finalize the trace split while preserving inline image positions.
        if message_parts:
            message_parts = normalize_message_parts_for_display(message_parts) or None

        self.response = bot_reply

        # 本文もUIパーツも空なら「回答なし」であり、成功として保存してはいけない。
        # 空の応答を保存すると空の吹き出しが残り、ユーザー発話だけが積み上がる。
        # An empty body with no UI parts means there is no answer at all, so it must
        # not be persisted as a success: an empty reply leaves a blank bubble behind
        # and the conversation ends up as a pile of unanswered user messages.
        if not bot_reply.strip() and not message_parts:
            logger.warning(
                "Chat generation produced an empty response.",
                extra={"model": self._model},
            )
            error_message = ERROR_CHAT_EMPTY_RESPONSE
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": True},
                invoke_error_callback=True,
            )
            return

        # このターンで取得した検索結果を直列化し、後続ターンで参照できるよう永続化する
        # Serialize this turn's search results so later turns can reference them.
        serialized_web_search = [
            serialize_web_search_result(
                with_web_search_citations(result, resolved_citations)
            )
            for result in web_search_results
            if result.has_sources
        ]

        try:
            persist_metadata = self._persist_once(
                bot_reply,
                message_parts,
                web_search_context=serialized_web_search or None,
            )
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
        if final_answer_incomplete is not None:
            if isinstance(final_answer_incomplete, FinalAnswerContinuationStalledError):
                message = "回答の続きを生成できず、途中までの回答を保存しました。"
            elif isinstance(final_answer_incomplete, LlmOutputLimitError):
                message = (
                    "回答が非常に長く、継続生成の上限に達しました。途中までの回答を保存しました。"
                )
            elif isinstance(final_answer_incomplete, LlmInputLimitError):
                message = (
                    "参照した情報が多すぎて、モデルが一度に扱える上限を超えました。"
                    "途中までの回答を保存しました。"
                )
            else:
                message = (
                    "AI提供元との接続が途中で終了しました。途中までの回答を保存しました。"
                )
            incomplete_payload = {
                **done_payload,
                "message": message,
                "partial": True,
                "retryable": (
                    isinstance(final_answer_incomplete, LlmOutputLimitError)
                    or is_retryable_llm_error(final_answer_incomplete)
                ),
                "continuations": continuation_count,
            }
            self._telemetry.final_answer_output_chars = len(bot_reply)
            self._telemetry.evidence_budget_consumed = evidence_context_budget.consumed
            logger.info(
                "Chat generation ended with a persisted partial answer.",
                extra={
                    "terminal_event": "incomplete",
                    "output_chars": len(bot_reply),
                    "duration_seconds": round(time.monotonic() - self.started_at, 3),
                    **self._telemetry.as_log_extra(),
                },
            )
            self._publish("incomplete", incomplete_payload, done=True)
            return
        self._telemetry.final_answer_output_chars = len(bot_reply)
        self._telemetry.evidence_budget_consumed = evidence_context_budget.consumed
        logger.info(
            "Chat generation completed.",
            extra={
                "terminal_event": "done",
                "output_chars": len(bot_reply),
                "duration_seconds": round(time.monotonic() - self.started_at, 3),
                **self._telemetry.as_log_extra(),
            },
        )
        self._publish("done", done_payload, done=True)


# ジェネレーションキーをビルドする関数
# Function to build the generation key
def build_generation_key(*, chat_room_id: str, user_id: int | None = None, sid: str | None = None) -> str:
    # 同じ room_id でもログインユーザーとゲストセッションは別の生成ジョブとして扱う。
    # これによりゲストの sid とユーザーIDの衝突や、共有 room_id による生成ロックの混線を防ぐ。
    # Treat logged-in users and guest sessions as different generation jobs even for the same room_id.
    # This prevents collisions between guest sids and user IDs, or crosstalk on generation locks due to shared room_ids.
    if user_id is not None:
        return f"user:{user_id}:{chat_room_id}"
    if sid is not None:
        return f"guest:{sid}:{chat_room_id}"
    raise ValueError("Either user_id or sid is required to build a generation key.")


# チャット生成サービスを定義するクラス
# Class defining the Chat Generation Service
class ChatGenerationService:
    # チャット応答生成ジョブを管理し、SSE の再接続・分散配信を吸収する。
    # ローカルプロセス内では `_jobs` にジョブを保持し、Redis が使える環境では
    # イベント履歴とアクティブロックを Redis にも書く。これにより、ロードバランサ配下で
    # 再接続先プロセスが変わっても、完了済み/実行中イベントを再生できる。
    #
    # Manages chat response generation jobs, smoothing over SSE reconnections and distributed delivery.
    # Keeps jobs in `_jobs` in the local process, and also writes event history and active locks to Redis
    # when available. This allows replaying completed/in-progress events even if the reconnected process
    # changes behind a load balancer.

    # サービスを初期化する
    # Initialize the service
    def __init__(
        self,
        *,
        job_retention_seconds: int = JOB_RETENTION_SECONDS,
        active_job_lock_ttl_seconds: int = DEFAULT_ACTIVE_JOB_LOCK_TTL_SECONDS,
        distributed_stream_idle_timeout_seconds: float = (
            DEFAULT_DISTRIBUTED_STREAM_IDLE_TIMEOUT_SECONDS
        ),
        sse_heartbeat_seconds: float = DEFAULT_SSE_HEARTBEAT_SECONDS,
        remote_cancel_timeout_seconds: float = DEFAULT_REMOTE_CANCEL_TIMEOUT_SECONDS,
        redis_client_getter: Callable[[], Any | None] | None = None,
    ) -> None:
        self._job_retention_seconds = job_retention_seconds
        self._active_job_lock_ttl_seconds = max(active_job_lock_ttl_seconds, 1)
        self._distributed_stream_idle_timeout_seconds = max(
            float(distributed_stream_idle_timeout_seconds),
            0.0,
        )
        self._sse_heartbeat_seconds = max(float(sse_heartbeat_seconds), 0.0)
        self._remote_cancel_timeout_seconds = max(float(remote_cancel_timeout_seconds), 0.0)
        self._redis_client_getter = redis_client_getter
        self._jobs: dict[str, ChatGenerationJob] = {}
        self._jobs_lock = threading.Lock()
        self._cancel_listener_thread: threading.Thread | None = None
        self._cancel_listener_lock = threading.Lock()

    # Redis クライアントを取得する
    # Retrieve the Redis client
    def _get_redis_client(self) -> Any | None:
        if self._redis_client_getter is not None:
            return self._redis_client_getter()
        return get_redis_client()

    # アクティブジョブの Redis ロックキーを生成する
    # Generate the Redis lock key for the active job
    def _active_lock_key(self, job_key: str) -> str:
        return f"{_ACTIVE_JOB_LOCK_KEY_PREFIX}:{job_key}"

    # 停止要求マーカーの Redis キーを生成する
    # Generate the Redis key for the stop-request marker
    def _cancel_request_key(self, job_key: str) -> str:
        return f"{_CANCEL_REQUEST_KEY_PREFIX}:{job_key}"

    # Redis に保存するイベントストリームのキーを生成する
    # Generate the Redis event stream key
    def _event_stream_key(self, job_key: str) -> str:
        return f"{_EVENT_STREAM_KEY_PREFIX}:{job_key}"

    # Redis Pub/Sub のイベントチャネル名を生成する
    # Generate the Redis Pub/Sub event channel name
    def _event_channel_name(self, job_key: str) -> str:
        return f"{_EVENT_CHANNEL_KEY_PREFIX}:{job_key}"

    # イベントオブジェクトを JSON 文字列にシリアライズする
    # Serialize the event object to a JSON string
    def _serialize_event(self, event: ChatGenerationEvent) -> str:
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
    def _deserialize_event(self, raw: str) -> ChatGenerationEvent | None:
        # Redis 上の古い/壊れた値はストリーム全体を落とさず読み飛ばす。
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

    # Redis 経由で分散イベントを配信する（リストへの追記および Pub/Sub 発行）
    # Publish a distributed event via Redis (append to list and publish via Pub/Sub)
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
            # Redis クライアント設定により bytes/str が混在しうる。ここでは str だけを扱い、
            # pub/sub 側の bytes デコードとは分けておく。
            if not isinstance(item, str):
                continue
            event = self._deserialize_event(item)
            if event is None:
                continue
            if event.sequence_id <= after_sequence_id:
                continue
            events.append(event)
        return events

    # 指定したジョブキーに対して Redis アクティブジョブロックの取得を試みる
    # Attempt to acquire the Redis active job lock for the specified job key
    def _try_acquire_active_job_lock(self, job_key: str) -> tuple[bool, str | None]:
        redis_client = self._get_redis_client()
        if redis_client is None:
            return True, None

        lock_key = self._active_lock_key(job_key)
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
            logger.exception(
                "Redis chat generation lock acquisition failed; falling back to in-memory."
            )
            return True, None

        if acquired:
            return True, lock_token
        return False, None

    # 自分が取得した Redis アクティブジョブロックを解放する
    # Release the Redis active job lock that was acquired by this instance
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
        # 自分が取得したロックだけを消すため、GET と DEL を Lua で不可分に実行する。
        # TTL 切れ後に別プロセスが取り直したロックを誤って解放しないため。
        try:
            redis_client.eval(lua_script, 1, self._active_lock_key(job_key), lock_token)
        except Exception:
            logger.exception("Redis chat generation lock release failed.")

    # 指定したジョブキーに対して Redis アクティブジョブロックが存在するか確認する
    # Check if a Redis active job lock exists for the specified job key
    def _has_distributed_active_lock(self, job_key: str) -> bool:
        redis_client = self._get_redis_client()
        if redis_client is None:
            return False
        try:
            return bool(redis_client.exists(self._active_lock_key(job_key)))
        except Exception:
            logger.exception("Redis chat generation lock existence check failed.")
            return False

    # 所有プロセス以外が取得したロックを強制的に削除する（応答不能なワーカー対策）
    # Force-delete an active lock held by an unresponsive worker
    def _force_release_active_job_lock(self, job_key: str) -> None:
        redis_client = self._get_redis_client()
        if redis_client is None:
            return
        try:
            redis_client.delete(self._active_lock_key(job_key))
        except Exception:
            logger.exception("Redis chat generation lock force release failed.")

    # 指定ジョブに対する停止要求マーカーが立っているかを確認する
    # Check whether a stop-request marker is set for the specified job
    def _is_remote_cancel_requested(self, job_key: str) -> bool:
        redis_client = self._get_redis_client()
        if redis_client is None:
            return False
        try:
            return bool(redis_client.exists(self._cancel_request_key(job_key)))
        except Exception:
            logger.exception("Redis chat generation cancel-request check failed.")
            return False

    # 停止要求マーカーを削除する（新しい生成ジョブが古い要求で止まらないようにする）
    # Clear the stop-request marker so a new job is not aborted by a stale request
    def _clear_remote_cancel_request(self, job_key: str) -> None:
        redis_client = self._get_redis_client()
        if redis_client is None:
            return
        try:
            redis_client.delete(self._cancel_request_key(job_key))
        except Exception:
            logger.exception("Redis chat generation cancel-request clear failed.")

    # プロセス内に実行中のジョブが残っているかを確認する
    # Check whether this process still holds a running job
    def _has_running_local_jobs(self) -> bool:
        with self._jobs_lock:
            return any(not job.is_done for job in self._jobs.values())

    # ローカルに保持しているジョブだけをキャンセルする
    # Cancel only the job held in this process
    def _cancel_local_job(self, job_key: str) -> bool:
        with self._jobs_lock:
            job = self._jobs.get(job_key)
        if job is None or job.is_done:
            return False
        job.cancel()
        return True

    # 停止要求を Pub/Sub で配信し、ジョブを所有するワーカーの停止完了を待つ
    # Broadcast the stop request and wait for the owning worker to release the lock
    def _request_remote_cancel(self, job_key: str) -> bool:
        redis_client = self._get_redis_client()
        if redis_client is None:
            return False
        if not self._has_distributed_active_lock(job_key):
            return False

        # マーカーは Pub/Sub 通知を取りこぼしたワーカーへの保険。
        # 生成ジョブ側が定期的に参照して自力で停止できるようにする。
        # The marker backs up the pub/sub notification: a worker that missed the message
        # still sees it while polling and stops on its own.
        try:
            redis_client.set(
                self._cancel_request_key(job_key),
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
            if not self._has_distributed_active_lock(job_key):
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
        self._force_release_active_job_lock(job_key)
        return True

    # 他ワーカーからの停止要求を購読し、自プロセスのジョブをキャンセルするループ
    # Subscribe to stop requests from other workers and cancel this process's jobs
    def _run_cancel_listener(self) -> None:
        redis_client = self._get_redis_client()
        if redis_client is None:
            self._release_cancel_listener_slot()
            return

        pubsub = None
        try:
            pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(_CANCEL_CHANNEL_NAME)
            while True:
                message = pubsub.get_message(timeout=1.0)
                if message and message.get("type") == "message":
                    job_key = _decode_redis_text(message.get("data"))
                    if job_key:
                        self._cancel_local_job(job_key)
                # 実行中ジョブが無くなったら購読を畳み、次の生成開始時に再購読する。
                # Stop subscribing once no job is running; the next job restarts the listener.
                if self._release_cancel_listener_slot_if_idle():
                    return
        except Exception:
            logger.exception("Chat generation cancel listener stopped unexpectedly.")
            self._release_cancel_listener_slot()
        finally:
            if pubsub is not None:
                try:
                    pubsub.close()
                except Exception:
                    logger.exception("Failed to close the chat generation cancel listener.")

    # 購読スレッドの登録を解除する
    # Deregister the listener thread slot
    def _release_cancel_listener_slot(self) -> None:
        with self._cancel_listener_lock:
            if self._cancel_listener_thread is threading.current_thread():
                self._cancel_listener_thread = None

    # 実行中ジョブが無い場合にだけ購読スレッドの登録を解除する
    # Deregister the listener thread slot only while no job is running
    def _release_cancel_listener_slot_if_idle(self) -> bool:
        with self._cancel_listener_lock:
            if self._has_running_local_jobs():
                return False
            if self._cancel_listener_thread is threading.current_thread():
                self._cancel_listener_thread = None
            return True

    # 停止要求を購読するスレッドが起動していることを保証する
    # Ensure the thread subscribing to stop requests is running
    def _ensure_cancel_listener(self) -> None:
        redis_client = self._get_redis_client()
        if redis_client is None or not hasattr(redis_client, "pubsub"):
            return
        with self._cancel_listener_lock:
            thread = self._cancel_listener_thread
            if thread is not None and thread.is_alive():
                return
            thread = threading.Thread(
                target=self._run_cancel_listener,
                name="chat-generation-cancel-listener",
                daemon=True,
            )
            self._cancel_listener_thread = thread
            thread.start()

    # Redis が有効で分散ストリーミングに対応しているかを確認する
    # Check if Redis is enabled and supports distributed streaming
    def supports_distributed_streaming(self) -> bool:
        return self._get_redis_client() is not None

    # メモリ上のジョブ状態をリセットし、必要に応じて実行中ジョブをキャンセルする
    # Reset the in-memory job state and optionally cancel running jobs
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

    # 実行中のすべてのジョブが完了するのを待機する
    # Wait for all running jobs to complete
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

    # 保存期間を過ぎて期限切れとなった完了済みジョブをメモリから削除する
    # Remove expired completed jobs from memory based on retention time
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

    # 指定ジョブをキャンセルし、キャンセルできたか否かを返す
    # Cancel the specified job and return whether the cancellation succeeded
    def cancel_generation_job(self, job_key: str) -> bool:
        if self._cancel_local_job(job_key):
            return True
        # 複数ワーカー構成では停止リクエストがジョブ非所有のワーカーに届くことがある。
        # その場合でもロックを解放しないと、ルームが生成中のまま再生成を拒否し続ける。
        # Under multiple workers the stop request can land on a worker that does not own the
        # job. Without this the lock survives and the room keeps rejecting regeneration.
        return self._request_remote_cancel(job_key)

    # 指定したジョブキーで現在生成処理が実行中であるか確認する
    # Check if a generation process is currently running for the specified job key
    def has_active_generation(self, job_key: str) -> bool:
        self._cleanup_expired_jobs()
        with self._jobs_lock:
            job = self._jobs.get(job_key)
            if job is not None:
                return not job.is_done
        return self._has_distributed_active_lock(job_key)

    # 再生可能な生成処理（メモリ上または Redis 上にイベントがある）が存在するか確認する
    # Check if a replayable generation process (with events in-memory or Redis) exists
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

    # 指定したジョブキーに対応するローカルジョブオブジェクトを取得する
    # Retrieve the local job object corresponding to the specified job key
    def get_generation_job(self, job_key: str) -> ChatGenerationJob | None:
        self._cleanup_expired_jobs()
        with self._jobs_lock:
            return self._jobs.get(job_key)

    # メモリまたは Redis Pub/Sub から生成イベントをイテレートして呼び出し元にストリームする
    # Iterate and stream generation events to the caller from memory or Redis Pub/Sub
    def iter_generation_events(
        self,
        job_key: str,
        *,
        after_sequence_id: int = 0,
    ) -> Iterator[ChatGenerationEvent | None]:
        job = self.get_generation_job(job_key)
        if job is not None:
            yield from job.iter_events(
                after_sequence_id=after_sequence_id,
                heartbeat_seconds=self._sse_heartbeat_seconds,
            )
            return

        # ローカルにジョブがない場合でも、Redis のイベント履歴があれば再接続として扱う。
        # これは複数プロセス構成で SSE 接続先が生成元と異なる場合に必要。
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
        next_heartbeat_at = time.monotonic() + self._sse_heartbeat_seconds
        try:
            pubsub.subscribe(channel)

            # subscribe 直前に list へ書かれたイベントを先に読む。
            # pub/sub は購読前のメッセージを保持しないため、この二段読みで取りこぼしを埋める。
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
                    raw_data = _decode_redis_text(message.get("data"))
                    if raw_data is not None:
                        deserialized_event = self._deserialize_event(raw_data)
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

                if not self.has_active_generation(job_key):
                    # ロック消滅直後は pub/sub の最後の通知がまだ届かないことがあるため、
                    # 終了判定の前に list をもう一度読んで終端イベントを回収する。
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

    # 新しいチャット応答生成ジョブを開始する
    # Start a new chat response generation job
    def start_generation_job(
        self,
        job_key: str,
        *,
        conversation_messages: list[dict[str, Any]],
        model: str,
        persist_response: Callable[..., dict[str, Any] | None],
        on_finished: Callable[[], None] | None = None,
        on_error: Callable[[], None] | None = None,
        prior_web_search_results: list[WebSearchResult] | None = None,
        personal_knowledge_search: Callable[[str], dict[str, Any]] | None = None,
        shared_prompt_search: Callable[[str], dict[str, Any]] | None = None,
        selected_reference_trace: list[SelectedReferenceLookupTrace] | None = None,
        ui_mode: GenerativeUiMode | str | None = None,
    ) -> ChatGenerationJob:
        self._cleanup_expired_jobs()
        acquired_lock, lock_token = self._try_acquire_active_job_lock(job_key)
        if not acquired_lock:
            raise ChatGenerationAlreadyRunningError(job_key)

        # 直前のジョブに対する停止要求が残っていると新しいジョブが即座に止まるため消す。
        # Drop any leftover stop request so the new job is not aborted by the previous one.
        self._clear_remote_cancel_request(job_key)

        # Redis ロックを先に取り、次にプロセス内の `_jobs` を確認する。
        # 逆順だと別プロセスとの競合を検出できず、同じ room で二重生成が走りうる。
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
                prior_web_search_results=prior_web_search_results,
                is_cancel_requested=lambda: self._is_remote_cancel_requested(job_key),
                personal_knowledge_search=personal_knowledge_search,
                shared_prompt_search=shared_prompt_search,
                selected_reference_trace=selected_reference_trace,
                ui_mode=ui_mode,
            )
            self._jobs[job_key] = job

        # 購読スレッドは `_jobs_lock` の外で起動する（ロック順序を固定して待ち合わせを避ける）。
        # Start the listener outside `_jobs_lock` to keep the lock ordering consistent.
        self._ensure_cancel_listener()

        try:
            job.start()
        except Exception:
            # start に失敗したジョブはリプレイ対象に残さず、分散ロックも即時解放する。
            with self._jobs_lock:
                self._jobs.pop(job_key, None)
            self._release_active_job_lock(job_key, lock_token)
            raise
        return job

    # ジョブを正常またはエラー終了後にクリーンアップ（ロック解放やコールバック実行）する
    # Clean up the job after normal or error completion (release lock, run callbacks)
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


# アプリケーション状態またはデフォルトから ChatGenerationService のインスタンスを取得する
# Retrieve the ChatGenerationService instance from the application state or default
def get_chat_generation_service(request: Request = None) -> ChatGenerationService:
    if request is not None:
        app = request.scope.get("app")
        state = getattr(app, "state", None)
        service = getattr(state, "chat_generation_service", None)
        if isinstance(service, ChatGenerationService):
            return service
    return _default_chat_generation_service


# メモリ上のすべての生成ジョブの状態をクリアする
# Clear the state of all in-memory generation jobs
def clear_generation_job_state(*, cancel_running: bool = False) -> None:
    get_chat_generation_service().reset_in_memory_state(cancel_running=cancel_running)


# 指定したジョブをキャンセルする
# Cancel the specified job
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


# 指定したジョブで生成が進行中であるかを判定する
# Determine if a generation is currently active for the specified job
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


# 指定したジョブを取得する
# Retrieve the specified generation job
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


# 指定したジョブがリプレイ可能であるかを判定する
# Determine if the specified job is replayable
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


# 指定したジョブのイベントストリームをイテレートする
# Iterate the event stream of the specified generation job
def iter_generation_events(
    job_key: str,
    *,
    after_sequence_id: int = 0,
    service: ChatGenerationService | None = None,
) -> Iterator[ChatGenerationEvent | None]:
    target = (
        service
        if isinstance(service, ChatGenerationService)
        else get_chat_generation_service()
    )
    return target.iter_generation_events(
        job_key,
        after_sequence_id=after_sequence_id,
    )


# 指定したパラメータで新しいチャット生成ジョブを開始する
# Start a new chat generation job with the specified parameters
def start_generation_job(
    job_key: str,
    *,
    conversation_messages: list[dict[str, Any]],
    model: str,
    persist_response: Callable[..., dict[str, Any] | None],
    on_finished: Callable[[], None] | None = None,
    on_error: Callable[[], None] | None = None,
    service: ChatGenerationService | None = None,
    prior_web_search_results: list[WebSearchResult] | None = None,
    personal_knowledge_search: Callable[[str], dict[str, Any]] | None = None,
    shared_prompt_search: Callable[[str], dict[str, Any]] | None = None,
    selected_reference_trace: list[SelectedReferenceLookupTrace] | None = None,
    ui_mode: GenerativeUiMode | str | None = None,
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
        prior_web_search_results=prior_web_search_results,
        personal_knowledge_search=personal_knowledge_search,
        shared_prompt_search=shared_prompt_search,
        selected_reference_trace=selected_reference_trace,
        ui_mode=ui_mode,
    )
