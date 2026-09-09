from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, TimeoutError
from typing import Any

from fastapi import Request

from services.error_messages import ERROR_CHAT_EMPTY_RESPONSE
from services.generative_ui import (
    GenerativeUiMode,
    NormalizedGenerativeResponse,
    normalize_response_with_artifact_retry,
    normalize_response_with_artifacts,
)
from services.message_parts_display import (
    GENERATIVE_UI_PART_TYPES,
    MAX_WEB_SEARCH_IMAGES_PER_REPLY,
    WEB_SEARCH_IMAGE_PART_TYPE,
    normalize_message_parts_for_display,
)

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
from .chat_context_recovery import build_recovery_base_messages
from .chat_evidence_store import (
    GET_EVIDENCE_TOOL_NAME,
    EvidenceStore,
    get_evidence_tool_definition,
)
from .chat_generation_coordinator import (
    REMOTE_CANCEL_CHECK_INTERVAL_SECONDS,
    ChatGenerationCoordinator,
    ChatGenerationEvent,
    # blueprints が `services.chat_generation` から直接 import しているため再エクスポートする。
    # Re-exported because the blueprints import it straight from `services.chat_generation`.
    ChatGenerationStreamTimeoutError,  # noqa: F401
)
from .chat_generation_telemetry import ChatGenerationTelemetry
from .chat_generation_turn import ChatTurnRunState, ModelDecision
from .chat_input_budget import (
    estimate_messages_chars,
)
from .chat_prompt import insert_after_leading_system_messages
from .chat_turn_state import (
    TurnStateUpdateFilter,
    build_turn_loop_messages,
    parse_turn_state_update,
    strip_turn_state_update,
    strip_turn_state_update_chunks,
)
from .chat_web_page_reader import (
    READ_WEB_PAGE_TOOL_NAME,
    WebPageReader,
    read_web_page_tool_definition,
)
from .llm import (
    LlmAuthenticationError,
    LlmConfigurationError,
    LlmInputLimitError,
    LlmOutputLimitError,
    LlmRateLimitError,
    LlmRetryableProviderError,
    LlmServiceError,
    LlmToolSchemaError,
    get_llm_response,
    get_llm_response_stream,
    is_retryable_llm_error,
)
from .llm_context_budget import (
    estimate_request_tokens,
    get_context_budget,
    request_fits_context,
)
from .personal_knowledge import (
    PERSONAL_KNOWLEDGE_TOOL_NAME,
    get_personal_knowledge_tool_definition,
)
from .research_state import (
    TurnState,
    TurnStateProjectionError,
)
from .selected_reference_context import (
    PERSONAL_KNOWLEDGE_SOURCE,
    SHARED_PROMPT_SOURCE,
    SelectedReferenceLookupTrace,
)
from .shared_prompt_lookup import (
    SHARED_PROMPT_TOOL_NAME,
    get_shared_prompt_tool_definition,
)
from .web_search import (
    WEB_SEARCH_ERROR_QUOTA_EXCEEDED,
    WEB_SEARCH_ERROR_REQUEST_FAILED,
    WEB_SEARCH_MAX_CONTEXT_CHARS,
    WEB_SEARCH_TOOL_CONTEXT_MAX_CHARS,
    WebEvidenceContextBudget,
    WebSearchCitation,
    WebSearchQuotaExceededError,
    WebSearchResult,
    build_web_search_evidence_policy_message,
    combine_web_search_results,
    create_web_evidence_context_budget,
    create_web_page_fetch_budget,
    get_web_search_tool_definition,
    is_web_search_enabled,
    normalize_search_language,
    normalize_web_search_freshness,
    resolve_web_search_citations,
    search_brave_llm_context,
    serialize_web_search_result_for_storage,
    split_web_search_citation_stream_text,
    strip_web_search_citation_html,
    with_web_search_citations,
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
# 停止要求が別ワーカーへ届いた場合に、所有ワーカーの応答を待つ上限。
# Upper bound for waiting on the owning worker after a stop request lands on another worker.
DEFAULT_REMOTE_CANCEL_TIMEOUT_SECONDS = 5.0


def _latest_user_message_text(messages: list[dict[str, Any]]) -> str:
    """Return the latest user prompt for request-aware UI recovery."""
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else str(content or "")
    return ""


# 完了したターンにユーザーが読める回答があるかを判定する。検索画像だけ・トレースだけは回答ではない。
# Decide whether a finished turn carries an answer the user can read; images or a trace alone are not one.
def _has_user_facing_answer(
    *,
    model_text: str,
    response_text: str,
    message_parts: list[dict[str, Any]] | None,
) -> bool:
    """Return whether a finished turn carries an answer the user can read.

    モデルが本文を書いたか（正規化前の生テキスト）、または生成UIがあるかで判定する。
    正規化で本文が消えた場合は、テキストと検索画像以外のパーツがあるときだけ回答扱いにする。
    Answered means the model wrote body text (raw, before normalization) or produced a
    generated UI. If normalization emptied the body, only parts other than text and
    web-search images keep the turn answered.
    """
    parts = [part for part in (message_parts or []) if isinstance(part, dict)]
    has_generative_ui = any(part.get("type") in GENERATIVE_UI_PART_TYPES for part in parts)
    if not model_text.strip() and not has_generative_ui:
        return False
    if response_text.strip():
        return True
    return any(
        part.get("type") not in (WEB_SEARCH_IMAGE_PART_TYPE, "text") for part in parts
    )


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
        # 日本語: モデルがツール呼び出し風のテキストを壊れた JSON で返した場合。通常の本文として扱います。
        # English: The model returned tool-call-looking text as broken JSON; treat it as ordinary content.
        logger.debug("Discarded malformed tool-call JSON from the model response.", exc_info=True)
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


# ツール引数として渡されたテキストを、型が揺れていても安全に文字列へ寄せる
# Coerce a tool argument into text, tolerating whatever type the model produced
# スキーマ検証をプロバイダに任せない以上、引数の型はこちらで受け止める。文字列以外
# （数値・文字列の配列など）でも実行を止めず、解釈できない値だけを空文字にする。
# Since provider-side schema validation is no longer relied upon, the argument types are
# absorbed here. Non-strings (numbers, a list of strings) still run; only values that
# cannot be read at all become an empty string.
def _tool_argument_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return " ".join(_tool_argument_text(entry) for entry in value).strip()
    return ""


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
    for item, source in zip(sources, result.sources, strict=True):
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
        # 直前のモデルストリームが出力上限で打ち切られたか。回答なら継続生成へ回す。
        # Whether the last model stream was cut off by the output cap; an answer then
        # continues instead of being persisted as if the model had finished.
        self._last_stream_output_limited = False
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
            pending_text = strip_turn_state_update("".join(self._pending_stream_chunks))
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
                # 書き直しを接合できない場合は本文を丸ごと捨て、二重化を優先して防ぐ。
                # If a rewrite cannot be spliced, drop it rather than duplicating the answer.
                pending_text = spliced_pending if spliced_pending is not None else ""
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
            # 日本語: 待機対象のタスクが失敗しても完了状態の返却は続けます。原因追跡のため記録します。
            # English: Keep returning the completion state even when the awaited task failed; record why.
            logger.debug("Waiting for the generation task failed.", exc_info=True)
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
        self._last_stream_output_limited = False
        # プロバイダがツール呼び出しを拒否したときだけ、ツールなしで同じステップをやり直す。
        # Only a provider-side tool-call rejection replays the same step without tools.
        current_tools = tools
        while True:
            emitted = False
            attempt_chunks: list[str] = []
            try:
                # Check the complete provider request before opening a stream.  The legacy
                # compactor only counted Web tool JSON and could miss system context, tool
                # schemas, or assistant tool-call metadata.
                if not request_fits_context(
                    current_messages,
                    self._model,
                    generation_phase,
                    current_tools,
                ):
                    budget = get_context_budget(
                        self._model,
                        generation_phase,
                        current_tools,
                    )
                    raise LlmInputLimitError(
                        "The prepared LLM request exceeds the model context budget "
                        f"(estimated={estimate_request_tokens(current_messages, current_tools)}, "
                        f"available={budget.available_input_tokens})."
                    )
                for chunk in get_llm_response_stream(
                    current_messages,
                    self._model,
                    tools=current_tools,
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
                self._last_stream_output_limited = True
                if discard_partial_on_retry:
                    buffered = list(attempt_chunks)
                    self._pending_stream_chunks.clear()
                    yield from buffered
                return
            except LlmToolSchemaError as exc:
                # プロバイダがモデルのツール呼び出しをスキーマ検証で拒否した場合、同じ要求を
                # 再送しても同じ拒否になる。ツールを外して1度だけやり直し、ターン全体を
                # 落とさずに手持ちの情報で回答へ進む。
                # A provider that rejected the model's tool call rejects the identical request
                # again. Replay the step once without tools so the turn degrades to an answer
                # from what is already known instead of failing outright.
                if (
                    current_tools is None
                    or (emitted and not discard_partial_on_retry)
                    or self._cancelled
                ):
                    raise
                logger.warning(
                    "Provider rejected a tool call; replaying the step without tools "
                    "(model=%s, phase=%s): %s",
                    self._model,
                    generation_phase,
                    exc,
                )
                self._telemetry.tool_schema_recoveries += 1
                current_tools = None
                if discard_partial_on_retry:
                    self._pending_stream_chunks.clear()
                continue
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
            else:
                if discard_partial_on_retry:
                    self._pending_stream_chunks.clear()
                    yield from attempt_chunks
                return

    # 検索系ツールの結果を回答トレースの1ステップへ変換する。参照元はイベント種別から決まる。
    # Turn a lookup tool result into one answer-trace step; the source follows the event prefix.
    @staticmethod
    def _lookup_trace_step(
        event_prefix: str,
        payload: dict[str, Any],
        query: str,
    ) -> TraceStep:
        return selected_reference_step(
            (
                PERSONAL_KNOWLEDGE_SOURCE
                if event_prefix == "personal_knowledge_search"
                else SHARED_PROMPT_SOURCE
            ),
            payload,
            query=query,
        )

    # 検索系ツール呼び出しの受け付け判定フェーズ。実行できない場合は結果を積んで None を返す。
    # The admission phase for a lookup tool call; on refusal it appends the tool result
    # and returns None instead of a step and query.
    def _begin_lookup_tool_call(
        self,
        tool_call: dict[str, Any],
        *,
        tool_name: str,
        search: Callable[[str], dict[str, Any]] | None,
        event_prefix: str,
        current_messages: list[dict[str, Any]],
        budget: AgentStepBudget,
        turn_state: TurnState,
    ) -> tuple[int, str] | None:
        if budget.tool_calls_exhausted:
            current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "step_limit_reached",
                        "message": "The search limit has been reached.",
                    },
                )
            )
            return None

        step = budget.start_tool_call()
        self._telemetry.tool_calls = budget.tool_calls
        self._telemetry.lookup_call_count += 1

        if search is None:
            turn_state.record_search(tool_name=tool_name, status="unsupported_tool")
            current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "unsupported_tool",
                        "message": f"Unsupported tool: {tool_name}",
                    },
                )
            )
            return None

        args_raw = tool_call.get("function", {}).get("arguments", "{}")
        try:
            args = json.loads(args_raw)
        except Exception:
            # 日本語: モデルが渡したツール引数が JSON として壊れていた場合は空引数として扱います。
            # English: Treat tool arguments the model produced as empty when they are not valid JSON.
            logger.debug("Discarded malformed tool-call arguments from the model.", exc_info=True)
            args = {}
        if not isinstance(args, dict):
            args = {}

        query = _tool_argument_text(args.get("query"))
        if not query:
            turn_state.record_search(tool_name=tool_name, status="invalid_arguments")
            current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "invalid_arguments",
                        "message": "Search query is empty.",
                    },
                )
            )
            return None
        self._publish(
            f"{event_prefix}_started",
            {"query": query, "step": step, "max_steps": budget.max_steps},
        )
        return step, query

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
        turn_state: TurnState,
        evidence_store: EvidenceStore,
        trace_steps: list[TraceStep] | None = None,
    ) -> None:
        admitted = self._begin_lookup_tool_call(
            tool_call,
            tool_name=tool_name,
            search=search,
            event_prefix=event_prefix,
            current_messages=current_messages,
            budget=budget,
            turn_state=turn_state,
        )
        if admitted is None:
            return
        step, query = admitted
        # 受け付け判定を通った時点で search は None ではない。
        # Admission guarantees a callable search here.
        try:
            payload = search(query)  # type: ignore[misc]
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
            turn_state.record_search(
                tool_name=tool_name,
                query=query,
                status="failed",
            )
            if trace_steps is not None:
                trace_steps.append(
                    self._lookup_trace_step(event_prefix, {"status": "failed"}, query)
                )
            return

        # 参照元が「検索できなかった」と返した場合も障害として扱う。0件として通すと、
        # UI もモデルも「該当なし」と伝えてしまう。
        # A source reporting that it could not search is a failure too. Passing it through as a
        # zero-hit result would make both the UI and the model claim that nothing matched.
        status = str(payload.get("status") or "")
        evidence_refs = evidence_store.add_reference_payload(
            payload,
            source_type=event_prefix,
            query=query,
        )
        turn_state.record_search(
            tool_name=tool_name,
            query=query,
            evidence_refs=evidence_refs,
            status=status or "ok",
        )
        if status == "failed":
            logger.warning("%s (status=failed)", failure_log_message)
            self._publish(
                f"{event_prefix}_failed",
                {"query": query, "step": step, "max_steps": budget.max_steps},
            )
            current_messages.append(_tool_result_message(tool_call, payload))
            if trace_steps is not None:
                trace_steps.append(self._lookup_trace_step(event_prefix, payload, query))
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
        if trace_steps is not None and status != "already_searched":
            trace_steps.append(self._lookup_trace_step(event_prefix, payload, query))

    # ターン開始時の状態を組み立てる。既存の参照根拠と選択済み参照をここで取り込む。
    # Build the turn's starting state, seeding it with prior evidence and selected references.
    def _build_turn_run_state(self) -> ChatTurnRunState:
        budget = AgentStepBudget.from_environment()
        telemetry = self._telemetry
        # 根拠の予算は許可されたツール実行回数から算出する。予算が回数に足りないと、
        # 後半の検索が「中身ゼロで成功した検索結果」に化けてモデルを誤誘導する。
        # Size the evidence budget from the permitted tool calls: a budget that cannot cover
        # them turns later searches into "successful" results with no content at all.
        evidence_context_budget = create_web_evidence_context_budget(budget.max_tool_calls)
        telemetry.evidence_budget_max_chars = evidence_context_budget.max_chars
        latest_user_message = _latest_user_message_text(self._conversation_messages)
        evidence_store = EvidenceStore()
        # 原文は初期値。最初のモデル判断で履歴を踏まえた目的へ更新する。
        # The raw request is a seed; the first model decision resolves it in context.
        turn_state = TurnState(objective=latest_user_message)
        state = ChatTurnRunState(
            # キャンセル時に保存できるよう、インスタンス側のチャンクリストを共有する。
            # Share the instance chunk list so a cancel can persist the partial text.
            chunks=self._chunks,
            telemetry=telemetry,
            budget=budget,
            page_fetch_budget=create_web_page_fetch_budget(),
            evidence_context_budget=evidence_context_budget,
            evidence_store=evidence_store,
            web_page_reader=WebPageReader(evidence_store),
            turn_state=turn_state,
            turn_base_messages=[dict(message) for message in self._conversation_messages],
            latest_user_message=latest_user_message,
            selected_web_search_images=self._selected_web_search_images,
            continuation_state_filter=TurnStateUpdateFilter(),
            web_search_trace_steps=selected_reference_steps(self._selected_reference_trace),
        )
        for prior_result in self._prior_web_search_results:
            turn_state.record_search(
                tool_name="web_search",
                query=prior_result.query,
                searched_at=prior_result.searched_at,
                freshness=prior_result.freshness,
                evidence_refs=evidence_store.add_web_result(prior_result),
                status="prior_turn",
            )
        for selected_trace in self._selected_reference_trace:
            selected_refs = evidence_store.add_reference_payload(
                selected_trace.payload,
                source_type=selected_trace.source,
                query=selected_trace.query,
            )
            turn_state.record_search(
                tool_name=selected_trace.source,
                query=selected_trace.query,
                evidence_refs=selected_refs,
                status=str(selected_trace.payload.get("status") or "ok"),
            )
        return state

    # 検索結果が届いた時点で表示候補の画像を選ぶ。停止しても露出済み画像を保存できる。
    # Select images as soon as a search result arrives so a stop still keeps revealed ones.
    def _collect_web_search_image_selections(
        self,
        state: ChatTurnRunState,
        result: WebSearchResult | None,
    ) -> None:
        selected_web_search_images = state.selected_web_search_images
        if result is None or len(selected_web_search_images) >= MAX_WEB_SEARCH_IMAGES_PER_REPLY:
            return
        try:
            selections = choose_web_search_images(
                state.latest_user_message,
                result,
                model=self._model,
                answer_text=state.streamed_display_text,
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
        self._publish_stream_text_with_images(state, "")

    # 表示本文を1チャンク配信し、画像挿入位置の基準となる累積テキストを進める。
    # Publish one display chunk and advance the accumulated text that anchors image offsets.
    def _publish_stream_chunk(self, state: ChatTurnRunState, text: str) -> None:
        if not text:
            return
        self._publish("chunk", {"text": text})
        state.streamed_display_text += text

    # 本文を配信しつつ、確定したオフセットで検索画像を露出する（過去本文も対象）。
    # Emit text and reveal images at stable offsets, including past text.
    def _publish_stream_text_with_images(self, state: ChatTurnRunState, text: str) -> None:
        pending_text = text
        while True:
            raw_parts_update = _build_streaming_parts_update("".join(state.chunks))
            if raw_parts_update is not None:
                if pending_text:
                    self._publish_stream_chunk(state, pending_text)
                return

            image_parts = build_web_search_image_parts(state.selected_web_search_images)
            next_image = find_next_streaming_image_insertion(
                f"{state.streamed_display_text}{pending_text}",
                image_parts,
                revealed_indices=set(state.revealed_image_indices),
                after_offset=state.revealed_image_offsets[-1] if state.revealed_image_offsets else 0,
            )
            if next_image is None:
                if pending_text:
                    self._publish_stream_chunk(state, pending_text)
                return

            insertion_offset, image_index = next_image
            current_text_length = len(state.streamed_display_text)
            relative_offset = insertion_offset - current_text_length
            if relative_offset < 0:
                relative_offset = 0
            if relative_offset > len(pending_text):
                if pending_text:
                    self._publish_stream_chunk(state, pending_text)
                return

            if relative_offset:
                self._publish_stream_chunk(state, pending_text[:relative_offset])
            state.revealed_image_indices.append(image_index)
            state.revealed_image_offsets.append(insertion_offset)
            visible_image_parts = [
                image_parts[index] for index in state.revealed_image_indices
            ]
            visible_parts = build_web_search_image_parts_at_offsets(
                state.streamed_display_text,
                visible_image_parts,
                state.revealed_image_offsets,
                keep_empty_tail=True,
            )
            self._publish(
                "response_parts_updated",
                {
                    "response": state.streamed_display_text,
                    "parts": visible_parts,
                },
            )
            pending_text = pending_text[relative_offset:]

    # ツール要求が無いと確定したモデルステップだけを、引用解決とUIパーツ更新込みで配信する。
    # Publish a model step only after confirming it requested no tools.
    def _publish_completed_answer_step(
        self,
        state: ChatTurnRunState,
        step_chunks: list[str],
    ) -> None:
        chunks = state.chunks
        for raw_chunk in step_chunks:
            chunk = raw_chunk
            if not chunks:
                combined_web_search_result = combine_web_search_results(state.web_search_results)
                if state.web_search_trace_steps or combined_web_search_result is not None:
                    state.web_search_trace_steps.append(answer_step(state.web_search_results))
                trace_block = build_web_search_trace_markdown(
                    combined_web_search_result,
                    steps=state.web_search_trace_steps,
                )
                if trace_block:
                    chunk = f"{trace_block}\n\n{chunk}"

            chunks.append(chunk)
            streaming_evidence = combine_web_search_results(
                [*state.web_search_results, *self._prior_web_search_results]
            )
            # モデルが真似て書いたチップHTMLは、検索根拠の有無にかかわらず
            # 表示前に取り除く。正規のチップはこの後の解決処理だけが描画する。
            # Chip markup echoed by the model is removed before display whether or
            # not this turn has evidence; only the resolution below renders chips.
            complete_stream_text, state.streaming_citation_buffer = (
                split_web_search_citation_stream_text(
                    f"{state.streaming_citation_buffer}{chunk}"
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
                self._publish_stream_text_with_images(state, stream_text)
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
                if streaming_parts_signature != state.last_streaming_parts_signature:
                    state.last_streaming_parts_signature = streaming_parts_signature
                    self._publish("response_parts_updated", streaming_parts_update)

    # 継続生成の1チャンクを、繰り返し届く内部状態の封筒を除いて配信する。
    # Publish one continuation chunk, minus any repeated state envelope.
    def _publish_answer_chunk(self, state: ChatTurnRunState, chunk: str) -> None:
        visible = state.continuation_state_filter.feed(chunk)
        if visible:
            self._publish_completed_answer_step(state, [visible])

    # 継続パスの未配信バッファをジョブ側へ預ける。停止・切断でも保存経路に載る。
    # Hand the continuation pass's undelivered buffer to the job so a stop or a
    # disconnect still routes it through the persistence path.
    def _adopt_continuation_buffer(self, buffer: list[str]) -> None:
        self._pending_stream_chunks = buffer
        self._pending_stream_is_rewrite = False

    # 継続パスが全文の書き直しへ切り替わったことを停止経路へ伝える。
    # Tell the cancellation path when a continuation has switched to a full rewrite.
    def _set_continuation_buffer_mode(self, is_rewrite: bool) -> None:
        self._pending_stream_is_rewrite = is_rewrite

    # 出力上限で切れた回答の続きだけを取り直すフェーズ。
    # The phase that fetches only the remainder of an answer cut off at the output cap.
    def _continue_interrupted_answer(
        self,
        state: ChatTurnRunState,
        answer_messages: list[dict[str, Any]],
        published_text: str,
    ) -> BaseException | None:
        """Continue an answer the provider cut off at its output cap.

        回答を書いたモデル判断だけが継続の対象で、別フェーズは作らない。すでに配信した
        本文を assistant 履歴として渡し、続きだけを同じループの延長として受け取る。
        Only the decision that wrote the answer is continued; no separate phase is created.
        The published text is replayed as assistant history so the provider returns just
        the remainder of the same answer.
        """
        telemetry = state.telemetry
        interruption = LlmOutputLimitError(
            "The answer stream stopped at the model output limit.",
            reason="max_output_tokens",
        )
        try:
            result = stream_final_answer_with_recovery(
                answer_messages,
                model=self._model,
                iter_stream=lambda messages, phase: self._iter_llm_stream_with_retry(
                    messages,
                    tools=None,
                    generation_phase=phase,
                ),
                publish_chunk=lambda chunk: self._publish_answer_chunk(state, chunk),
                publish_event=self._publish,
                should_stop=self._should_stop,
                adopt_buffer=self._adopt_continuation_buffer,
                adopt_buffer_mode=self._set_continuation_buffer_mode,
                answer_phase="agent",
                continuation_phase="continuation_deep",
                published_answer_text=published_text,
                published_answer_error=interruption,
            )
        finally:
            # 通常完了・入力超過・キャンセルのどの経路でも、次の保存処理が古い共有
            # バッファや書き直しモードを誤って拾わないようにする。
            # Clear shared state on every exit so later persistence cannot adopt a stale
            # continuation buffer or rewrite mode.
            self._pending_stream_chunks = []
            self._pending_stream_is_rewrite = False
        trailing = state.continuation_state_filter.flush()
        if trailing:
            self._publish_completed_answer_step(state, [trailing])
        state.continuation_count = result.continuation_count
        telemetry.continuation_count = result.continuation_count
        for reason in result.reasons:
            telemetry.record_continuation_reason(reason)
        telemetry.continuation_stalled = result.stalled
        telemetry.continuation_restart_trimmed = result.restart_trimmed
        telemetry.first_pass_finish_reason = interruption.reason
        return result.error

    # 1回のモデル判断へ渡す要求を TurnState と直近のツール結果だけから組み立てるフェーズ。
    # The phase that builds one decision request from TurnState plus only the newest tool result.
    def _prepare_turn_messages(
        self,
        state: ChatTurnRunState,
        latest_tool_exchange: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        force_answer: bool,
        minimal: bool = False,
        empty_answer_recovery: bool = False,
    ) -> list[dict[str, Any]] | None:
        """Build one decision request from TurnState plus only the newest tool result.

        ``minimal`` はプロバイダ側の拒否からの再構築用。生のツール結果を落とし、
        TurnState と直前の会話・最新の依頼で同じ判断をやり直す。
        ``minimal`` rebuilds after a provider-side rejection: the raw tool result is
        dropped and the same decision is retried with TurnState and the recent exchange.
        ``empty_answer_recovery`` は直前の判断が本文を返さなかった回復用で、
        回答のみ契約に短いメモを添える。
        ``empty_answer_recovery`` marks the retry after a decision that produced no
        user-facing answer; it adds a short note to the answer-only contract.
        """
        telemetry = state.telemetry
        phase = "agent"
        context_budget = get_context_budget(self._model, phase, tools)
        state_tokens = min(
            6_000,
            max(1_000, context_budget.available_input_tokens // 3),
        )

        def with_web_policy(
            projection: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            # 検索根拠を持つターンだけ、引用と回答の方針を1つのsystem指示として渡す。
            # A turn holding web evidence gets the citation and answering policy as one
            # system instruction; an ordinary chat turn never carries it.
            if not (state.web_search_results or self._prior_web_search_results):
                return projection
            return insert_after_leading_system_messages(
                projection,
                build_web_search_evidence_policy_message(),
            )

        if not minimal:
            try:
                projected = state.turn_state.projected_messages(
                    state.turn_base_messages,
                    max_tokens=state_tokens,
                )
            except TurnStateProjectionError:
                return None
            candidate = build_turn_loop_messages(
                [
                    *with_web_policy(projected),
                    *([] if force_answer else latest_tool_exchange),
                ],
                force_answer=force_answer,
                empty_answer_recovery=empty_answer_recovery,
            )
            if request_fits_context(candidate, self._model, phase, tools):
                telemetry.context_projection_count += 1
                return candidate

        try:
            minimal_projected = state.turn_state.projected_messages(
                build_recovery_base_messages(state.turn_base_messages),
                max_tokens=state_tokens,
            )
        except TurnStateProjectionError:
            return None
        minimal_candidate = build_turn_loop_messages(
            [
                *with_web_policy(minimal_projected),
                *([] if minimal or force_answer else latest_tool_exchange),
            ],
            force_answer=force_answer,
            empty_answer_recovery=empty_answer_recovery,
        )
        if request_fits_context(minimal_candidate, self._model, phase, tools):
            telemetry.context_projection_count += 1
            telemetry.context_recovery_count += 1
            return minimal_candidate
        return None

    # モデルへ提示するツール定義を決めるフェーズ。
    # The phase that decides which tool definitions the model is offered.
    def _configure_agent_tools(self, state: ChatTurnRunState) -> None:
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
        configured_tools.append(get_evidence_tool_definition())
        configured_tools.append(read_web_page_tool_definition())
        state.configured_tools = configured_tools
        state.telemetry.research_phase_used = bool(self._selected_reference_trace)

    # 単一判断ループ: TurnStateを見る → 必要ならツール → State更新 → 再判断。
    # ツール履歴全体は再送せず、直近の呼び出しと結果だけを次の判断へ渡す。
    # The single-decision loop: read TurnState, optionally run tools, update state, decide again.
    # Only the newest call and its result are replayed, never the whole tool history.
    def _run_agent_loop(self, state: ChatTurnRunState) -> bool:
        """Drive the decision loop; return True when a stop request ended the turn."""
        budget = state.budget
        telemetry = state.telemetry
        while True:
            if self._should_stop():
                return True

            available_tools = self._available_agent_tools(state)
            tools_withdrawn = not available_tools
            # 空回答の回復もツールなしの回答要求だが、予算枯渇とは別に記録する。
            # Empty-answer recovery is also a tool-free answer request, but it is
            # accounted separately from budget exhaustion.
            force_answer = tools_withdrawn or state.empty_answer_recovery_attempted
            active_tools = None if force_answer else available_tools
            if tools_withdrawn:
                telemetry.tools_withdrawn_by_budget = True
            turn_messages = self._prepare_turn_messages(
                state,
                state.current_messages,
                active_tools,
                force_answer=force_answer,
                minimal=state.minimal_context_required or state.tool_schema_recovery_attempted,
                empty_answer_recovery=state.empty_answer_recovery_attempted,
            )
            if turn_messages is None:
                telemetry.context_recovery_count += 1
                raise LlmInputLimitError(
                    "The complete TurnState does not fit the model context budget."
                )
            llm_step = budget.start_llm_turn()
            telemetry.llm_turns = budget.llm_turns

            if not state.suppress_next_generation_started:
                self._publish(
                    "response_generation_started",
                    {"step": llm_step, "max_steps": budget.max_steps},
                )
            state.suppress_next_generation_started = False

            decision = self._stream_model_decision(
                state,
                turn_messages,
                active_tools,
                force_answer=force_answer,
            )
            if decision.outcome == "stopped":
                return True
            if decision.outcome == "replay":
                continue

            if not decision.tool_calls:
                if self._finish_answer_step(
                    state,
                    turn_messages,
                    active_tools,
                    decision.step_chunks,
                ):
                    continue
                return False

            self._pending_stream_chunks = []
            self._pending_stream_is_rewrite = False
            telemetry.research_phase_used = True
            self._dispatch_tool_calls(state, decision.tool_calls, llm_step)

    # モデル判断1回をストリームし、本文チャンクとツール呼び出しへ振り分けるフェーズ。
    # The phase that streams one model decision and splits it into body chunks and tool calls.
    def _stream_model_decision(
        self,
        state: ChatTurnRunState,
        turn_messages: list[dict[str, Any]],
        active_tools: list[dict[str, Any]] | None,
        *,
        force_answer: bool,
    ) -> ModelDecision:
        tool_calls_buffer: list[dict[str, Any]] = []
        step_chunks: list[str] = []
        self._pending_stream_chunks = step_chunks
        self._pending_stream_is_rewrite = False
        try:
            for chunk in self._iter_llm_stream_with_retry(
                turn_messages,
                tools=active_tools,
                generation_phase="agent",
                discard_partial_on_retry=True,
                tolerate_output_limit=True,
            ):
                if self._should_stop():
                    return ModelDecision(outcome="stopped")
                if not chunk:
                    continue
                parsed_tool_calls = _parse_tool_calls_chunk(chunk)
                if parsed_tool_calls is not None:
                    tool_calls_buffer.extend(parsed_tool_calls)
                else:
                    step_chunks.append(chunk)
        except LlmInputLimitError:
            # 同じ要求を送り直しても同じ拒否になる。生のツール結果を捨て、
            # TurnState と直前の会話を残して同じ判断を1度だけやり直す。
            # Resending the identical request only repeats the rejection: drop the raw
            # tool result and retry once with TurnState and the recent exchange.
            if state.minimal_context_required or state.chunks:
                raise
            state.minimal_context_required = True
            state.telemetry.input_limit_recoveries += 1
            state.telemetry.context_recovery_count += 1
            self._pending_stream_chunks = []
            self._pending_stream_is_rewrite = False
            state.suppress_next_generation_started = True
            return ModelDecision(outcome="replay")
        except LlmToolSchemaError:
            # ツール予算切れ後のツールなし要求がモデルの逸脱で拒否された場合は、
            # 直前の会話を残し、ツール履歴を除いた最終回答要求へ1度だけ切り替える。
            # If the model violates the tool-free request after the budget is exhausted,
            # retry once with a compact final-answer request retaining the recent
            # conversation but excluding tool history.
            if (
                force_answer
                and active_tools is None
                and not state.tool_schema_recovery_attempted
                and not self._cancelled
            ):
                state.tool_schema_recovery_attempted = True
                state.telemetry.tool_schema_recoveries += 1
                self._pending_stream_chunks = []
                self._pending_stream_is_rewrite = False
                state.suppress_next_generation_started = True
                return ModelDecision(outcome="replay")
            raise

        if self._should_stop():
            return ModelDecision(outcome="stopped")

        state.turn_state.apply_model_update(parse_turn_state_update(step_chunks))
        return ModelDecision(
            outcome="decided",
            tool_calls=[] if force_answer else tool_calls_buffer,
            step_chunks=step_chunks,
        )

    # ツール要求の無い判断を回答として締めるフェーズ。回答のみ再試行が必要なら True を返す。
    # The phase that closes a tool-free decision as the answer; True asks for one answer-only retry.
    def _finish_answer_step(
        self,
        state: ChatTurnRunState,
        turn_messages: list[dict[str, Any]],
        active_tools: list[dict[str, Any]] | None,
        step_chunks: list[str],
    ) -> bool:
        telemetry = state.telemetry
        output_limited = self._last_stream_output_limited
        self._pending_stream_chunks = []
        self._pending_stream_is_rewrite = False
        # モデルの区切りをそのまま保ち、内部状態の封筒だけを取り除く。
        # Keep the model's own boundaries and drop only the internal envelope.
        visible_chunks = strip_turn_state_update_chunks(step_chunks)
        if (
            not visible_chunks
            and not state.chunks
            and not state.empty_answer_recovery_attempted
            and not self._cancelled
        ):
            # 封筒のみ・無出力・出力上限で本文ゼロは「回答なし」。ここで抜けると
            # 画像だけ／トレースだけの応答が完了扱いになるため、同じ判断を
            # 回答のみ要求で1度だけやり直す。
            # Envelope-only, empty, or cut off before any body text means no
            # answer. Breaking here would finish the turn as an image-only or
            # trace-only reply, so retry the same decision once, answer-only.
            state.empty_answer_recovery_attempted = True
            telemetry.empty_answer_recoveries += 1
            logger.warning(
                "Final decision produced no user-facing answer; retrying once "
                "as an answer-only request.",
                extra={
                    **telemetry.as_log_extra(),
                    "output_limited": output_limited,
                    "step_chars": len("".join(step_chunks)),
                },
            )
            state.suppress_next_generation_started = True
            return True
        state.answer_context_messages = turn_messages
        telemetry.final_answer_input_tokens = estimate_request_tokens(
            turn_messages,
            active_tools,
        )
        telemetry.final_answer_input_chars = estimate_messages_chars(turn_messages)
        telemetry.first_pass_finish_reason = (
            "max_output_tokens" if output_limited else "stop"
        )
        if visible_chunks:
            self._publish_completed_answer_step(state, visible_chunks)
            if output_limited:
                # 出力上限で切れた回答は成功完了にしない。同じ回答の続きだけを
                # 限定回数で取り直す。
                # An answer cut off at the output cap is not a success: fetch
                # only the remainder, a bounded number of times.
                state.final_answer_incomplete = self._continue_interrupted_answer(
                    state,
                    turn_messages,
                    "".join(visible_chunks),
                )
        return False

    # モデルが要求したツール呼び出しを種類別の実行部へ振り分けるフェーズ。
    # The phase that routes the model's requested tool calls to their per-tool runners.
    def _dispatch_tool_calls(
        self,
        state: ChatTurnRunState,
        tool_calls_buffer: list[dict[str, Any]],
        llm_step: int,
    ) -> None:
        normalized_tool_calls = [
            _normalize_tool_call(tool_call, step=llm_step, index=index)
            for index, tool_call in enumerate(tool_calls_buffer, start=1)
        ]
        assistant_tool_call_msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": normalized_tool_calls,
        }
        state.current_messages = [assistant_tool_call_msg]

        for tc in normalized_tool_calls:
            # ツールごとの実行と結果の追加
            # Execute each tool and append results
            func_name = tc.get("function", {}).get("name")
            available_names = {
                tool["function"]["name"] for tool in self._available_agent_tools(state)
            }
            if func_name not in available_names:
                self._record_unsupported_tool_call(state, tc, func_name)
                continue
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
                    current_messages=state.current_messages,
                    budget=state.budget,
                    turn_state=state.turn_state,
                    evidence_store=state.evidence_store,
                    trace_steps=state.web_search_trace_steps,
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
                    current_messages=state.current_messages,
                    budget=state.budget,
                    turn_state=state.turn_state,
                    evidence_store=state.evidence_store,
                    trace_steps=state.web_search_trace_steps,
                )
                continue

            if func_name in (GET_EVIDENCE_TOOL_NAME, READ_WEB_PAGE_TOOL_NAME):
                self._run_read_tool_call(state, tc)
                continue

            if func_name != "web_search":
                self._record_unsupported_tool_call(state, tc, func_name)
                continue

            self._run_web_search_tool_call(state, tc)

    @staticmethod
    def _available_agent_tools(state: ChatTurnRunState) -> list[dict[str, Any]]:
        """Withdraw exhausted search/read tools independently."""
        available = []
        for tool in state.configured_tools:
            name = tool["function"]["name"]
            if name == GET_EVIDENCE_TOOL_NAME:
                if state.budget.reads_exhausted or not len(state.evidence_store):
                    continue
            elif name == READ_WEB_PAGE_TOOL_NAME:
                if state.budget.reads_exhausted or not state.evidence_store.has_web_records():
                    continue
            elif state.budget.tool_calls_exhausted:
                continue
            available.append(tool)
        return available

    # 保存情報と既知URLの本文を、検索とは独立した読み取り予算で取得する。
    # Read stored evidence or a known page using a budget independent of searches.
    def _run_read_tool_call(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
    ) -> None:
        budget = state.budget
        name = tool_call.get("function", {}).get("name")
        if budget.reads_exhausted:
            payload = {
                "status": "step_limit_reached",
                "message": "The reading budget has been reached. Use the evidence already read.",
            }
        else:
            budget.start_read_call()
            state.telemetry.tool_calls = budget.tool_calls
            arguments = tool_call.get("function", {}).get("arguments", "{}")
            if name == READ_WEB_PAGE_TOOL_NAME:
                payload = state.web_page_reader.execute_read_web_page(
                    arguments, max_chars=budget.read_message_limit,
                )
                if payload.get("status") == "ok":
                    state.web_search_trace_steps.append(TraceStep(
                        title="参照先のページ本文を確認",
                        detail="以前に見つけたURLから、回答に必要な箇所を読みました。",
                        kind="read",
                    ))
            else:
                payload = state.evidence_store.execute_get_evidence(
                    arguments, max_chars=budget.read_message_limit,
                )
            budget.consume_read_chars(len(json.dumps(payload, ensure_ascii=False)))
            state.telemetry.evidence_read_count = budget.read_calls
            state.telemetry.read_budget_consumed = budget.read_chars
            state.turn_state.record_search(
                tool_name=str(name),
                status=str(payload.get("status") or "unknown"),
            )
        state.current_messages.append(_tool_result_message(tool_call, payload))

    # 未対応ツールの要求を記録し、モデルへ理由を返すフェーズ。
    # The phase that records an unsupported tool request and tells the model why.
    def _record_unsupported_tool_call(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
        func_name: Any,
    ) -> None:
        if not state.budget.tool_calls_exhausted:
            state.budget.start_tool_call()
        elif not state.budget.reads_exhausted:
            # 取り下げ済みツールを繰り返すモデルにも有限の試行回数を適用する。
            # An unavailable tool must not create an unbounded decision loop.
            state.budget.start_read_call()
        state.telemetry.tool_calls = state.budget.tool_calls
        state.turn_state.record_search(
            tool_name=str(func_name or "unknown_tool"),
            status="unsupported_tool",
        )
        state.current_messages.append(
            _tool_result_message(
                tool_call,
                {
                    "status": "unsupported_tool",
                    "message": f"Unsupported tool: {func_name}",
                },
            )
        )

    # Web検索ツールの要求1件を、引数正規化からキャッシュ判定・実行まで進めるフェーズ。
    # The phase that carries one web-search tool call from argument normalization
    # through the cache check to execution.
    def _run_web_search_tool_call(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
    ) -> None:
        budget = state.budget
        args_raw = tool_call.get("function", {}).get("arguments", "{}")
        try:
            args = json.loads(args_raw)
        except Exception:
            # 日本語: モデルが渡したツール引数が JSON として壊れていた場合は空引数として扱います。
            # English: Treat tool arguments the model produced as empty when they are not valid JSON.
            logger.debug("Discarded malformed tool-call arguments from the model.", exc_info=True)
            args = {}
        if not isinstance(args, dict):
            args = {}

        if budget.tool_calls_exhausted:
            state.current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "step_limit_reached",
                        "message": "The web search limit has been reached.",
                    },
                )
            )
            return

        search_step_index = budget.start_tool_call()
        state.telemetry.tool_calls = budget.tool_calls

        # プロバイダ側のスキーマ検証には頼らない。モデルが返した引数はここで
        # 正規化し、想定外の値は既定へ丸めてターンを進める。
        # Never rely on provider-side schema validation: normalize the model's
        # arguments here and round unexpected values to a default so the turn
        # keeps moving.
        query = _tool_argument_text(args.get("query"))
        freshness = normalize_web_search_freshness(args.get("freshness"))
        search_language = normalize_search_language(args.get("search_language"))
        if not query:
            state.turn_state.record_search(
                tool_name="web_search",
                status="invalid_arguments",
            )
            state.current_messages.append(
                _tool_result_message(
                    tool_call,
                    {
                        "status": "invalid_arguments",
                        "message": "Search query is empty.",
                    },
                )
            )
            return
        query_text = query
        freshness_text = freshness
        search_key = _normalized_search_key(
            query_text,
            freshness_text,
            search_language,
        )
        cached_result = state.web_search_results_by_key.get(search_key)

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
            self._reuse_cached_web_search(
                state,
                tool_call,
                cached_result,
                query_text=query_text,
                step=search_step_index,
            )
            return

        try:
            self._execute_web_search(
                state,
                tool_call,
                query_text=query_text,
                freshness_text=freshness_text,
                search_language=search_language,
                search_key=search_key,
                step=search_step_index,
            )
        except WebSearchQuotaExceededError as exc:
            self._report_web_search_quota_exceeded(
                state,
                tool_call,
                exc,
                query_text=query_text,
                step=search_step_index,
            )
        except Exception:
            self._report_web_search_failure(
                state,
                tool_call,
                query_text=query_text,
                step=search_step_index,
            )

    # 同一条件の検索結果を再利用するフェーズ。プロバイダへは問い合わせない。
    # The phase that reuses an identical earlier search instead of calling the provider.
    def _reuse_cached_web_search(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
        cached_result: WebSearchResult,
        *,
        query_text: str,
        step: int,
    ) -> None:
        cached_refs = state.evidence_store.add_web_result(cached_result)
        state.turn_state.record_search(
            tool_name="web_search",
            query=query_text,
            evidence_refs=cached_refs,
            searched_at=cached_result.searched_at,
            freshness=cached_result.freshness,
            status="cached",
        )
        state.web_search_trace_steps.extend(
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
                "step": step,
                "max_steps": state.budget.max_steps,
                "cached": True,
            },
        )
        self._collect_web_search_image_selections(state, cached_result)
        state.telemetry.cached_web_search_count += 1
        tool_payload = _budgeted_web_search_result_tool_payload(
            cached_result,
            state.evidence_context_budget,
            cached=True,
            telemetry=state.telemetry,
        )
        state.current_messages.append(
            _tool_result_message(
                tool_call,
                tool_payload,
            )
        )

    # 新規のWeb検索を実行し、根拠・トレース・ツール結果へ反映するフェーズ。
    # The phase that runs a fresh web search and folds it into evidence, trace and tool result.
    def _execute_web_search(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
        *,
        query_text: str,
        freshness_text: str,
        search_language: str,
        search_key: tuple[str, str, str],
        step: int,
    ) -> None:
        result = search_brave_llm_context(
            query_text,
            freshness=freshness_text,
            page_fetch_budget=state.page_fetch_budget,
            language_hint=state.latest_user_message,
            search_language=search_language,
        )
        state.web_search_results_by_key[search_key] = result
        state.web_search_trace_steps.extend(
            [
                search_step(result, additional=bool(state.web_search_results)),
                *page_reading_steps(result),
                review_step(result),
            ]
        )
        if result.has_sources:
            state.web_search_results.append(result)
        result_refs = state.evidence_store.add_web_result(result)
        state.turn_state.record_search(
            tool_name="web_search",
            query=query_text,
            evidence_refs=result_refs,
            searched_at=result.searched_at,
            freshness=result.freshness,
            status="ok" if result.has_sources else "no_sources",
        )
        state.telemetry.web_search_count += 1
        self._publish(
            "web_search_completed",
            {
                "query": result.query,
                "source_count": len(result.sources),
                "step": step,
                "max_steps": state.budget.max_steps,
                "cached": False,
            },
        )
        self._collect_web_search_image_selections(state, result)
        tool_payload = _budgeted_web_search_result_tool_payload(
            result,
            state.evidence_context_budget,
            telemetry=state.telemetry,
        )
        state.current_messages.append(
            _tool_result_message(
                tool_call,
                tool_payload,
            )
        )

    # 月間上限に達した検索を、ターンを落とさずに記録・通知するフェーズ。
    # The phase that records and announces a quota-exhausted search without failing the turn.
    def _report_web_search_quota_exceeded(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
        exc: WebSearchQuotaExceededError,
        *,
        query_text: str,
        step: int,
    ) -> None:
        message = (
            f"Web検索の月間上限（全体 {exc.limit} 回）に達しました。"
            "検索なしで回答を続けます。"
        )
        logger.warning(
            "Web search quota exceeded mid-turn (limit=%s, retry_after_seconds=%s); "
            "continuing the turn without this search.",
            exc.limit,
            exc.retry_after_seconds,
            extra=self._telemetry.as_log_extra(),
        )
        state.web_search_trace_steps.append(
            search_failed_step(
                query_text,
                reason="月間上限に達したため検索結果を取得できませんでした。",
            )
        )
        state.suppress_next_generation_started = True
        self._publish(
            "web_search_failed",
            {
                "query": query_text,
                "code": WEB_SEARCH_ERROR_QUOTA_EXCEEDED,
                "message": message,
                "retry_after_seconds": exc.retry_after_seconds,
                "step": step,
                "max_steps": state.budget.max_steps,
            },
        )
        state.current_messages.append(
            _tool_result_message(
                tool_call,
                {
                    "status": "quota_exceeded",
                    "message": message,
                    "retry_after_seconds": exc.retry_after_seconds,
                },
            )
        )
        state.turn_state.record_search(
            tool_name="web_search",
            query=query_text,
            status="quota_exceeded",
        )

    # 検索リクエスト自体が失敗した場合に、取得済みの情報で続行させるフェーズ。
    # The phase that keeps the turn going on already gathered evidence when a search request fails.
    def _report_web_search_failure(
        self,
        state: ChatTurnRunState,
        tool_call: dict[str, Any],
        *,
        query_text: str,
        step: int,
    ) -> None:
        logger.exception("Brave search via tool call failed.")
        state.web_search_trace_steps.append(
            search_failed_step(
                query_text,
                reason="検索リクエストに失敗したため、取得済みの情報で回答を続けました。",
            )
        )
        state.suppress_next_generation_started = True
        self._publish(
            "web_search_failed",
            {
                "query": query_text,
                "code": WEB_SEARCH_ERROR_REQUEST_FAILED,
                "message": "Web検索に失敗しました。検索なしで回答を続けます。",
                "step": step,
                "max_steps": state.budget.max_steps,
            },
        )
        state.current_messages.append(
            _tool_result_message(
                tool_call,
                {
                    "status": "failed",
                    "message": "Web search failed.",
                },
            )
        )
        state.turn_state.record_search(
            tool_name="web_search",
            query=query_text,
            status="failed",
        )

    # 引用チップ判定のために保留していた末尾を、ループ終了後に配信するフェーズ。
    # The phase that flushes the tail held back for citation-chip detection once the loop ends.
    def _flush_streaming_citation_buffer(self, state: ChatTurnRunState) -> None:
        if not state.streaming_citation_buffer:
            return
        streaming_evidence = combine_web_search_results(
            [*state.web_search_results, *self._prior_web_search_results]
        )
        buffered_text = strip_web_search_citation_html(
            state.streaming_citation_buffer
        )
        if streaming_evidence is not None:
            buffered_text = resolve_web_search_citations(
                buffered_text,
                streaming_evidence,
            ).text
        if buffered_text:
            self._publish_stream_text_with_images(state, buffered_text)

    # 生成失敗をユーザー向けイベントと運用ログの両方へ落とすフェーズ。
    # The phase that turns a generation failure into both a user event and an operations log.
    def _report_generation_failure(
        self,
        exc: Exception,
        state: ChatTurnRunState,
    ) -> None:
        if self._cancelled:
            return
        # 本文を1文字も出していない場合だけ、呼び出し元のエラーコールバックを起動する。
        # Only a turn that emitted no body text at all invokes the caller's error callback.
        invoke_error_callback = not state.chunks
        if isinstance(exc, LlmConfigurationError):
            logger.exception(
                "Chat generation stopped due to an LLM configuration error.",
                extra=self._telemetry.as_log_extra(),
            )
            error_message = str(exc) or "LLM設定エラーが発生しました。"
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": False},
                invoke_error_callback=invoke_error_callback,
            )
            return
        if isinstance(exc, LlmAuthenticationError):
            logger.exception(
                "Chat generation stopped due to an LLM provider authentication error.",
                extra=self._telemetry.as_log_extra(),
            )
            error_message = "LLMプロバイダ認証エラーが発生しました。設定を確認してください。"
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": False},
                invoke_error_callback=invoke_error_callback,
            )
            return
        if isinstance(exc, LlmRateLimitError):
            logger.warning(
                "Chat generation hit an LLM provider rate limit (retry_after_seconds=%s): %s",
                exc.retry_after_seconds,
                exc,
                exc_info=exc,
                extra=self._telemetry.as_log_extra(),
            )
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
                invoke_error_callback=invoke_error_callback,
            )
            return
        if isinstance(exc, LlmInputLimitError):
            logger.warning(
                "Chat generation stopped because the request exceeded the model context window.",
                exc_info=exc,
                extra=self._telemetry.as_log_extra(),
            )
            error_message = (
                "参照した情報が多すぎて、モデルが一度に扱える上限を超えました。"
                "質問を分けるか、参照を減らして再試行してください。"
            )
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": True},
                invoke_error_callback=invoke_error_callback,
            )
            return
        if isinstance(exc, LlmServiceError):
            retryable = is_retryable_llm_error(exc)
            if retryable:
                error_message = "一時的な内部エラーが発生しました。時間をおいて再試行してください。"
            else:
                error_message = "内部エラーが発生しました。"
            logger.exception(
                "Chat generation stopped due to an LLM service error (retryable=%s).",
                retryable,
                extra={**self._telemetry.as_log_extra(), "llm_error_type": exc.__class__.__name__},
            )
            self._handle_error(
                error_message,
                {"message": error_message, "retryable": retryable},
                invoke_error_callback=invoke_error_callback,
            )
            return
        logger.exception(
            "Unexpected error while generating chat response.",
            extra=self._telemetry.as_log_extra(),
        )
        error_message = "内部エラーが発生しました。"
        self._handle_error(
            error_message,
            {"message": error_message, "retryable": False},
            invoke_error_callback=invoke_error_callback,
        )

    # 生成本文を正規化するフェーズ。途中終了したターンは生成UIの再試行を行わない。
    # The phase that normalizes the generated body; a truncated turn skips the generated-UI retry.
    def _normalize_final_answer(
        self,
        state: ChatTurnRunState,
        bot_reply: str,
        latest_user_message: str,
    ) -> NormalizedGenerativeResponse:
        if state.final_answer_incomplete is not None:
            return normalize_response_with_artifacts(
                bot_reply,
                recover_truncated=True,
                ui_mode=self._ui_mode,
            )
        return normalize_response_with_artifact_retry(
            bot_reply,
            conversation_messages=state.answer_context_messages or state.current_messages,
            model=self._model,
            generate_response=get_llm_response,
            user_request=latest_user_message,
            ui_mode=self._ui_mode,
        )

    # 引用markerを検証済みソースへのリンクへ解決するフェーズ。
    # The phase that resolves citation markers into links to verified sources.
    def _resolve_final_citations(
        self,
        state: ChatTurnRunState,
        bot_reply: str,
        message_parts: list[dict[str, Any]] | None,
    ) -> tuple[str, list[dict[str, Any]] | None, tuple[WebSearchCitation, ...]]:
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
            [*state.web_search_results, *self._prior_web_search_results]
        )
        resolved_citations: tuple[WebSearchCitation, ...] = ()
        if citation_evidence is None:
            return bot_reply, message_parts, resolved_citations

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
        return bot_reply, message_parts, resolved_citations

    # 回答が無いターンを成功として保存せず、エラーとして通知するフェーズ。
    # The phase that reports an answerless turn as an error instead of persisting it.
    def _report_empty_response(self, state: ChatTurnRunState, model_text: str) -> None:
        logger.warning(
            "Chat generation produced an empty response.",
            extra={
                **self._telemetry.as_log_extra(),
                "has_model_text": bool(model_text.strip()),
                "selected_image_count": len(state.selected_web_search_images),
            },
        )
        error_message = ERROR_CHAT_EMPTY_RESPONSE
        self._handle_error(
            error_message,
            {"message": error_message, "retryable": True},
            invoke_error_callback=True,
        )

    # 途中終了の理由をユーザー向け文言へ変換する。
    # Translate why the answer ended early into a user-facing sentence.
    @staticmethod
    def _partial_answer_message(error: BaseException) -> str:
        if isinstance(error, FinalAnswerContinuationStalledError):
            return "回答の続きを生成できず、途中までの回答を保存しました。"
        if isinstance(error, LlmOutputLimitError):
            return "回答が非常に長く、継続生成の上限に達しました。途中までの回答を保存しました。"
        if isinstance(error, LlmInputLimitError):
            return (
                "参照した情報が多すぎて、モデルが一度に扱える上限を超えました。"
                "途中までの回答を保存しました。"
            )
        return "AI提供元との接続が途中で終了しました。途中までの回答を保存しました。"

    # 応答を履歴へ保存し、done / incomplete の終端イベントを発行するフェーズ。
    # The phase that persists the reply and publishes the terminal done / incomplete event.
    def _persist_and_publish_result(
        self,
        state: ChatTurnRunState,
        bot_reply: str,
        message_parts: list[dict[str, Any]] | None,
        resolved_citations: tuple[WebSearchCitation, ...],
    ) -> None:
        # このターンで取得した検索結果を直列化し、後続ターンで参照できるよう永続化する
        # Serialize this turn's search results so later turns can reference them.
        serialized_web_search = [
            serialize_web_search_result_for_storage(
                with_web_search_citations(result, resolved_citations)
            )
            for result in state.web_search_results
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
        self._telemetry.final_answer_output_chars = len(bot_reply)
        self._telemetry.evidence_budget_consumed = state.evidence_context_budget.consumed
        if state.final_answer_incomplete is not None:
            incomplete_payload = {
                **done_payload,
                "message": self._partial_answer_message(state.final_answer_incomplete),
                "partial": True,
                "retryable": (
                    isinstance(state.final_answer_incomplete, LlmOutputLimitError)
                    or is_retryable_llm_error(state.final_answer_incomplete)
                ),
                "continuations": state.continuation_count,
            }
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

    # 生成結果を正規化・引用解決・画像配置してから保存と終端通知へ渡すフェーズ。
    # The phase that normalizes, resolves citations and places images before persisting.
    def _finalize_generation(self, state: ChatTurnRunState) -> None:
        # モデルが本文を書いたかは、正規化や画像配置の前に生の chunks で確定する。
        # 本文ゼロのターンにトレースだけを前置して完了扱いにはしない。
        # Whether the model wrote any body text is settled from the raw chunks before
        # normalization and image placement. A turn with no body never gets a trace-only body.
        model_text = "".join(state.chunks)
        latest_user_message = _latest_user_message_text(self._conversation_messages)
        normalized_response = self._normalize_final_answer(
            state,
            model_text,
            latest_user_message,
        )
        if normalized_response.validation_errors:
            logger.warning(
                "One or more generated UI artifacts failed validation and were omitted.",
                extra={"validation_errors": normalized_response.validation_errors},
            )
        bot_reply = normalized_response.text
        message_parts = normalized_response.parts

        bot_reply, message_parts, resolved_citations = self._resolve_final_citations(
            state,
            bot_reply,
            message_parts,
        )

        # 画像は検索結果を取得した時点で選定済み。引用解決後は、選定LLMが返した
        # 配置計画を本文へ反映し、ストリーム中に表示した順序と保存内容を一致させる。
        # Image selection already happened when each search result arrived. After
        # citation resolution, realize the placement plan returned by the selector
        # so persisted history matches what the stream revealed.
        if state.selected_web_search_images:
            message_parts = append_web_search_image_parts(
                message_parts,
                state.selected_web_search_images,
                fallback_text=bot_reply,
            )

        # トレースを独立パーツへ分け、本文内の画像位置を維持したまま保存・配信する。
        # Finalize the trace split while preserving inline image positions.
        if message_parts:
            message_parts = normalize_message_parts_for_display(message_parts) or None

        self.response = bot_reply

        # 本文も生成UIも無ければ「回答なし」であり、成功として保存してはいけない。
        # 検索画像やトレースだけでは回答にならない。空の応答を保存すると空の吹き出し
        # （画像だけ・ステップだけの吹き出し）が残り、ユーザー発話だけが積み上がる。
        # No body and no generated UI means there is no answer at all, so it must not be
        # persisted as a success: search images or a trace alone are not an answer, and an
        # empty reply leaves a blank (image-only / steps-only) bubble behind while
        # unanswered user messages pile up.
        if not _has_user_facing_answer(
            model_text=model_text,
            response_text=bot_reply,
            message_parts=message_parts,
        ):
            self._report_empty_response(state, model_text)
            return

        self._persist_and_publish_result(
            state,
            bot_reply,
            message_parts,
            resolved_citations,
        )

    # バックグラウンドスレッドで実行されるチャット応答生成の入口。各フェーズを順に呼ぶだけ。
    # Entry point of chat response generation on the background thread; it only sequences phases.
    def _run(self) -> None:
        state = self._build_turn_run_state()
        try:
            if self._should_stop():
                return

            self._configure_agent_tools(state)
            if self._run_agent_loop(state):
                return
            self._flush_streaming_citation_buffer(state)

        # エラーハンドリング
        # ユーザーへエラーを表示する経路は必ずログにも詳細を残す方針のため、各分岐で
        # exc_info 付きのログを出す（呼び出し元の llm.py 側で既にログ済みの例外でも、
        # ここでは会話ターンのテレメトリ（モデル・ステップ数・調査有無など）を紐付けて
        # 再度記録し、どのターンで失敗したかを追えるようにする）。
        # Error handling. Every branch that surfaces an error to the user must also leave a
        # detailed log entry. Even though llm.py already logs the raw provider exception, log
        # again here with this turn's telemetry (model, step count, whether research/tool use
        # was in progress) so failures mid-loop (research → web search → answer) are traceable
        # to the specific turn, not just the provider call.
        except Exception as exc:
            self._report_generation_failure(exc, state)
            return

        if self._should_stop():
            return

        self._finalize_generation(state)


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
        # プロセス間協調（Redis Pub/Sub・分散ロック・停止要求）は専用のコラボレータへ委譲する。
        # ローカルジョブの操作だけをコールバックとして渡し、ライフサイクルはこのクラスが持つ。
        # Cross-process coordination (pub/sub, the distributed lock, stop requests) is delegated
        # to a dedicated collaborator; only local job operations are handed to it as callbacks
        # so the job lifecycle stays here.
        self._coordinator = ChatGenerationCoordinator(
            job_retention_seconds=self._job_retention_seconds,
            active_job_lock_ttl_seconds=self._active_job_lock_ttl_seconds,
            distributed_stream_idle_timeout_seconds=self._distributed_stream_idle_timeout_seconds,
            sse_heartbeat_seconds=self._sse_heartbeat_seconds,
            remote_cancel_timeout_seconds=self._remote_cancel_timeout_seconds,
            cancel_local_job=self._cancel_local_job,
            has_running_local_jobs=self._has_running_local_jobs,
            redis_client_getter=redis_client_getter,
        )

    # Redis クライアントを取得する
    # Retrieve the Redis client
    def _get_redis_client(self) -> Any | None:
        return self._coordinator.get_redis_client()

    # アクティブジョブの Redis ロックキーを生成する
    # Generate the Redis lock key for the active job
    def _active_lock_key(self, job_key: str) -> str:
        return self._coordinator.active_lock_key(job_key)

    # 停止要求マーカーの Redis キーを生成する
    # Generate the Redis key for the stop-request marker
    def _cancel_request_key(self, job_key: str) -> str:
        return self._coordinator.cancel_request_key(job_key)

    # Redis に保存するイベントストリームのキーを生成する
    # Generate the Redis event stream key
    def _event_stream_key(self, job_key: str) -> str:
        return self._coordinator.event_stream_key(job_key)

    # Redis Pub/Sub のイベントチャネル名を生成する
    # Generate the Redis Pub/Sub event channel name
    def _event_channel_name(self, job_key: str) -> str:
        return self._coordinator.event_channel_name(job_key)

    # イベントオブジェクトを JSON 文字列にシリアライズする
    # Serialize the event object to a JSON string
    def _serialize_event(self, event: ChatGenerationEvent) -> str:
        return self._coordinator.serialize_event(event)

    # JSON 文字列をイベントオブジェクトにデシリアライズする
    # Deserialize a JSON string to an event object
    def _deserialize_event(self, raw: str) -> ChatGenerationEvent | None:
        return self._coordinator.deserialize_event(raw)

    # Redis 経由で分散イベントを配信する（リストへの追記および Pub/Sub 発行）
    # Publish a distributed event via Redis (append to list and publish via Pub/Sub)
    def _publish_distributed_event(self, job_key: str, event: ChatGenerationEvent) -> None:
        self._coordinator.publish_event(job_key, event)

    # Redis のイベントストリームから指定されたシーケンスIDより後のイベントを読み出す
    # Read events from the Redis event stream after the specified sequence ID
    def _read_distributed_events(
        self,
        job_key: str,
        *,
        after_sequence_id: int = 0,
    ) -> list[ChatGenerationEvent]:
        return self._coordinator.read_events(
            job_key,
            after_sequence_id=after_sequence_id,
        )

    # 指定したジョブキーに対して Redis アクティブジョブロックの取得を試みる
    # Attempt to acquire the Redis active job lock for the specified job key
    def _try_acquire_active_job_lock(self, job_key: str) -> tuple[bool, str | None]:
        return self._coordinator.try_acquire_active_job_lock(job_key)

    # 自分が取得した Redis アクティブジョブロックを解放する
    # Release the Redis active job lock that was acquired by this instance
    def _release_active_job_lock(self, job_key: str, lock_token: str | None) -> None:
        self._coordinator.release_active_job_lock(job_key, lock_token)

    # 指定したジョブキーに対して Redis アクティブジョブロックが存在するか確認する
    # Check if a Redis active job lock exists for the specified job key
    def _has_distributed_active_lock(self, job_key: str) -> bool:
        return self._coordinator.has_active_lock(job_key)

    # 所有プロセス以外が取得したロックを強制的に削除する（応答不能なワーカー対策）
    # Force-delete an active lock held by an unresponsive worker
    def _force_release_active_job_lock(self, job_key: str) -> None:
        self._coordinator.force_release_active_job_lock(job_key)

    # 指定ジョブに対する停止要求マーカーが立っているかを確認する
    # Check whether a stop-request marker is set for the specified job
    def _is_remote_cancel_requested(self, job_key: str) -> bool:
        return self._coordinator.is_remote_cancel_requested(job_key)

    # 停止要求マーカーを削除する（新しい生成ジョブが古い要求で止まらないようにする）
    # Clear the stop-request marker so a new job is not aborted by a stale request
    def _clear_remote_cancel_request(self, job_key: str) -> None:
        self._coordinator.clear_remote_cancel_request(job_key)

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
        return self._coordinator.request_remote_cancel(job_key)

    # 他ワーカーからの停止要求を購読し、自プロセスのジョブをキャンセルするループ
    # Subscribe to stop requests from other workers and cancel this process's jobs
    def _run_cancel_listener(self) -> None:
        self._coordinator.run_cancel_listener()

    # 購読スレッドの登録を解除する
    # Deregister the listener thread slot
    def _release_cancel_listener_slot(self) -> None:
        self._coordinator.release_cancel_listener_slot()

    # 実行中ジョブが無い場合にだけ購読スレッドの登録を解除する
    # Deregister the listener thread slot only while no job is running
    def _release_cancel_listener_slot_if_idle(self) -> bool:
        return self._coordinator.release_cancel_listener_slot_if_idle()

    # 停止要求を購読するスレッドが起動していることを保証する
    # Ensure the thread subscribing to stop requests is running
    def _ensure_cancel_listener(self) -> None:
        self._coordinator.ensure_cancel_listener()

    # Redis が有効で分散ストリーミングに対応しているかを確認する
    # Check if Redis is enabled and supports distributed streaming
    def supports_distributed_streaming(self) -> bool:
        return self._coordinator.supports_distributed_streaming()

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

        return self._coordinator.has_replay_history(job_key)

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
        # A job absent from this process is still a reconnection when Redis holds its event
        # history, which happens whenever the SSE connection lands on another worker.
        yield from self._coordinator.iter_distributed_events(
            job_key,
            after_sequence_id=after_sequence_id,
            has_active_generation=self.has_active_generation,
        )

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
