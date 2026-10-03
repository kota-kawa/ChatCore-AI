"""LLM のストリームを、一時的な障害の再試行とツール拒否からの回復を含めて読むフェーズ。

The phase that reads the LLM stream, retrying transient failures and recovering from tool rejections.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from typing import Any

from .chat_generation_job_base import ChatGenerationJobBase
from .chat_tool_calls import _parse_tool_calls_chunk
from .chat_turn_state import build_tool_rejection_messages
from .llm import (
    LlmInputLimitError,
    LlmOutputLimitError,
    LlmRetryableProviderError,
    LlmToolSchemaError,
    get_llm_response_stream,
)
from .llm_context_budget import (
    estimate_request_tokens,
    get_context_budget,
    request_fits_context,
)
from .llm_protocol_leak import ProtocolLeakGuard

logger = logging.getLogger(__name__)


# 出力開始前の一時的なプロバイダ障害を再試行する回数と待機時間
# Retry budget and backoff for transient provider failures before any output is emitted.
DEFAULT_LLM_STREAM_MAX_RETRIES = 3
LLM_STREAM_RETRY_BASE_DELAY_SECONDS = 1.0
LLM_STREAM_RETRY_MAX_DELAY_SECONDS = 8.0
# プロバイダが Retry-After でこれより長い待機を指示した場合は、その場での再試行を
# あきらめる。生成ターンを何十秒も止めるより、ここまでの結果を返すほうが速い。
# Give up retrying in place when the provider asks for a longer wait than this: returning what
# the turn already has beats holding the generation open for tens of seconds.
LLM_STREAM_RETRY_MAX_WAIT_SECONDS = 8.0


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


# プロバイダが指示した待機秒数が、このターンの中で待てる長さかを判定する。
# Report whether the wait the provider asked for is short enough to sit through.
def _is_retry_delay_affordable(exc: BaseException) -> bool:
    retry_after = getattr(exc, "retry_after_seconds", None)
    if not isinstance(retry_after, int) or retry_after <= 0:
        return True
    return retry_after <= LLM_STREAM_RETRY_MAX_WAIT_SECONDS


# バッファ済みのチャンク列の末尾から指定文字数を取り除く（プロトコル漏れの目印がチャンク境界を
# またいでいた場合に、前のチャンクへ入った目印の頭を消す）。
# Drop the given number of characters from the end of buffered chunks, removing the head of a
# protocol-leak marker that began in an earlier chunk.
def _trim_chunks_tail(chunks: list[str], chars: int) -> None:
    while chars > 0 and chunks:
        last = chunks.pop()
        if len(last) > chars:
            chunks.append(last[: len(last) - chars])
            return
        chars -= len(last)


# LLM ストリームの読み取りと再試行を担う Mixin
# Mixin that reads the LLM stream and retries it
class ChatGenerationLlmStreamMixin(ChatGenerationJobBase):
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
        # プロバイダがツール呼び出しを拒否したときだけ、同じステップをツール付きで1度引き直し、
        # それでも拒否されたらツールなしでやり直す。
        # Only a provider-side tool-call rejection resamples the same step once with its tools,
        # then replays it without tools if it is rejected again.
        current_tools = tools
        rejection_base_messages = current_messages
        tool_schema_retried = False
        while True:
            emitted = False
            attempt_chunks: list[str] = []
            leak_guard = ProtocolLeakGuard()
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
                stream = get_llm_response_stream(
                    current_messages,
                    self._model,
                    tools=current_tools,
                    generation_phase=generation_phase,
                )
                try:
                    for chunk in stream:
                        if self._should_stop():
                            return
                        emitted = True
                        # ツール呼び出しの JSON は本文ではないので、引数の文字列で誤検出しないよう素通しする。
                        # 保留中の本文を先に出し、ツール呼び出しとの前後を保つ。
                        # Tool-call JSON is not body text; pass it through so its arguments cannot trip
                        # the guard, after the held-back text so the order is kept.
                        if _parse_tool_calls_chunk(chunk) is None:
                            pieces: tuple[str, ...] = (leak_guard.feed(chunk),)
                        else:
                            pieces = (leak_guard.flush(), chunk)
                        for piece in pieces:
                            if discard_partial_on_retry:
                                if leak_guard.tripped:
                                    _trim_chunks_tail(attempt_chunks, leak_guard.overflow_chars)
                                if piece:
                                    attempt_chunks.append(piece)
                                with self._chunks_lock:
                                    self._pending_stream_chunks[:] = attempt_chunks
                            elif piece:
                                yield piece
                        if leak_guard.tripped:
                            # 漏れの先は回答ではない。読み続けると出力上限まで費用と時間だけが増える。
                            # Nothing past the leak is an answer; reading on only burns tokens to the cap.
                            self._telemetry.protocol_leak_truncations += 1
                            logger.warning(
                                "Stopped a stream where tool-call protocol leaked into the text "
                                "(model=%s, phase=%s).",
                                self._model,
                                generation_phase,
                            )
                            close_stream = getattr(stream, "close", None)
                            if callable(close_stream):
                                close_stream()
                            break
                    tail = leak_guard.flush()
                    if discard_partial_on_retry:
                        if tail:
                            attempt_chunks.append(tail)
                    elif tail:
                        yield tail
                except Exception:
                    # 保留していた本文は受け取り済みの本文の続きなので、例外より先に渡す。途中で
                    # 失敗した回答を救うときも、この末尾まで含める。
                    # Held-back text continues what was already received, so release it before the
                    # error propagates; salvaging a failed answer must include this tail too.
                    tail = leak_guard.flush()
                    if tail and discard_partial_on_retry:
                        attempt_chunks.append(tail)
                        with self._chunks_lock:
                            self._pending_stream_chunks[:] = attempt_chunks
                    elif tail:
                        yield tail
                    raise
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
                    with self._chunks_lock:
                        self._pending_stream_chunks.clear()
                    yield from buffered
                return
            except LlmToolSchemaError as exc:
                self._telemetry.record_tool_schema_rejection(
                    reason=exc.reason,
                    tool_name=exc.tool_name,
                    offered_tool_names=[
                        str((tool.get("function") or {}).get("name") or "") for tool in current_tools or []
                    ],
                )
                if (
                    current_tools is None
                    or (emitted and not discard_partial_on_retry)
                    or self._cancelled
                ):
                    raise
                # 拒否はモデルが1回のサンプルで崩れたツール呼び出しを出したことを示すだけで、
                # ストリームは温度を固定しないため、引き直せば正しい呼び出しになりうる。
                # ツールを外すと、そのステップ以降はメモや根拠をもう読めないので、先に1度だけ
                # 同じツールで引き直す。
                # A rejection only means one sample produced a malformed call. Streams do not pin
                # the temperature, so a resample can come back well formed. Dropping the tools
                # ends any further reading for the turn, so resample once with the same tools first.
                if not tool_schema_retried:
                    tool_schema_retried = True
                    self._telemetry.tool_schema_retries += 1
                    current_messages = build_tool_rejection_messages(
                        rejection_base_messages,
                        [tool["function"]["name"] for tool in current_tools],
                    )
                    logger.warning(
                        "Provider rejected a tool call; resampling the step with its tools "
                        "(model=%s, phase=%s, reason=%s).",
                        self._model,
                        generation_phase,
                        exc.reason,
                    )
                    if discard_partial_on_retry:
                        with self._chunks_lock:
                            self._pending_stream_chunks.clear()
                    continue
                # 2度目の拒否では、ツールを外して1度だけやり直し、ターン全体を落とさずに
                # 手持ちの情報で回答へ進む。
                # On a second rejection, replay the step once without tools so the turn degrades
                # to an answer from what is already known instead of failing outright.
                logger.warning(
                    "Provider rejected a tool call; replaying the step without tools "
                    "(model=%s, phase=%s): %s",
                    self._model,
                    generation_phase,
                    exc,
                )
                self._telemetry.tool_schema_recoveries += 1
                current_tools = None
                current_messages = build_tool_rejection_messages(rejection_base_messages, ())
                if discard_partial_on_retry:
                    with self._chunks_lock:
                        self._pending_stream_chunks.clear()
                continue
            except LlmRetryableProviderError as exc:
                # レート制限もここで再試行する。1ターンに複数回のモデル判断を回す以上、
                # 429 は日常的に当たる。プロバイダが待機秒数を指示している場合はそれに
                # 従い、待ちきれない長さのときだけ即座に諦める。
                # Rate limits are retried here too: a turn that runs several model decisions
                # hits 429 routinely. Honour the provider's Retry-After and bail out only
                # when the wait it asks for is longer than this turn can hold.
                if (
                    (emitted and not discard_partial_on_retry)
                    or attempt >= max_retries
                    or self._cancelled
                    or not _is_retry_delay_affordable(exc)
                ):
                    raise
                if discard_partial_on_retry:
                    with self._chunks_lock:
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
                    with self._chunks_lock:
                        self._pending_stream_chunks.clear()
                    yield from attempt_chunks
                return
