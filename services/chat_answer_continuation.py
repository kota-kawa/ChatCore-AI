"""Bounded recovery for interrupted user-facing answer streams."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from .llm import (
    LlmInputLimitError,
    LlmOutputLimitError,
    LlmRateLimitError,
    LlmRetryableProviderError,
    LlmServiceError,
)

logger = logging.getLogger(__name__)

DEFAULT_FINAL_ANSWER_MAX_CONTINUATIONS = 3
FINAL_ANSWER_CONTINUATION_OVERLAP_CHARS = 2048
# 継続の先頭がここまで既存本文の先頭と一致したら「最初から書き直した」と判定する。
# 短すぎる一致は見出しの再掲などで普通に起きるため、文単位の長さを要求する。
# A continuation whose opening matches the start of the existing answer for at least this
# many characters is treated as a restart. Shorter matches happen legitimately (a repeated
# heading), so require a sentence-scale prefix.
FINAL_ANSWER_RESTART_PREFIX_CHARS = 160
# 書き直しを既存本文へ接合するときの錨。長い順に試し、見つからなければ接合を諦める。
# Anchors used to splice a rewritten continuation onto the existing answer, tried longest
# first; if none match, the pass is dropped instead of risking duplicated prose.
FINAL_ANSWER_RESTART_ANCHOR_CHARS = (320, 200, 120, 64)


class FinalAnswerContinuationStalledError(LlmOutputLimitError):
    """A continuation completed without adding any user-visible answer text."""

    def __init__(self) -> None:
        super().__init__(
            "Final answer continuation produced no new text.",
            reason="continuation_stalled",
        )


@dataclass(frozen=True)
class FinalAnswerRecoveryResult:
    error: LlmServiceError | None
    continuation_count: int
    reasons: tuple[str, ...] = ()
    stalled: bool = False
    restart_trimmed: bool = False


@dataclass
class _ContinuationPass:
    """Per-pass buffering state for one continuation attempt."""

    # 先頭だけを貯めて境界の重複を除去し、それ以降はそのまま流す。
    # Buffer only the opening so the boundary overlap can be removed, then stream the rest.
    buffer: list[str] = field(default_factory=list)
    buffered_chars: int = 0
    head_flushed: bool = False
    # 書き直しを検出したパスは全体を貯めてから既存本文へ接合する。
    # A pass detected as a rewrite buffers in full so it can be spliced onto the answer.
    full_buffer_mode: bool = False

    @property
    def text(self) -> str:
        return "".join(self.buffer)


def get_final_answer_max_continuations() -> int:
    raw = os.environ.get("LLM_FINAL_ANSWER_MAX_CONTINUATIONS")
    if raw is None:
        return DEFAULT_FINAL_ANSWER_MAX_CONTINUATIONS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_FINAL_ANSWER_MAX_CONTINUATIONS
    return max(value, 0)


def strip_continuation_overlap(existing: str, continuation: str) -> str:
    """Remove only an exact suffix/prefix overlap from a continuation response."""
    max_overlap = min(
        len(existing),
        len(continuation),
        FINAL_ANSWER_CONTINUATION_OVERLAP_CHARS,
    )
    for overlap in range(max_overlap, 0, -1):
        if existing[-overlap:] == continuation[:overlap]:
            return continuation[overlap:]
    return continuation


def looks_like_restarted_answer(existing: str, continuation: str) -> bool:
    """Report whether a continuation restarted the answer from the beginning."""
    prefix_length = min(
        len(existing),
        len(continuation),
        FINAL_ANSWER_RESTART_PREFIX_CHARS,
    )
    if prefix_length < FINAL_ANSWER_RESTART_PREFIX_CHARS:
        return False
    return existing[:prefix_length] == continuation[:prefix_length]


def splice_restarted_answer(existing: str, continuation: str) -> str | None:
    """Return only the text a rewritten continuation adds after the existing answer.

    既存本文の末尾を錨として書き直し本文の中を探し、その先だけを採用する。錨が
    見つからない場合は None を返し、本文の二重化を避けるためパスごと破棄させる。
    Locate the tail of the existing answer inside the rewrite and keep only what follows.
    Returning None makes the caller drop the pass rather than duplicate the prose.
    """
    for anchor_length in FINAL_ANSWER_RESTART_ANCHOR_CHARS:
        if len(existing) < anchor_length:
            continue
        anchor = existing[-anchor_length:]
        position = continuation.rfind(anchor)
        if position < 0:
            continue
        return continuation[position + anchor_length:]
    return None


def build_final_answer_continuation_messages(
    base_messages: list[dict[str, Any]],
    partial_answer: str,
) -> list[dict[str, Any]]:
    return [
        *(dict(message) for message in base_messages),
        {"role": "assistant", "content": partial_answer},
        {
            "role": "user",
            "content": (
                "Continue the same answer from exactly where it stopped. Output only the "
                "missing continuation: do not restart, summarize, repeat headings, mention "
                "the interruption, or shorten the remaining requested coverage. Finish every "
                "requirement from the original request."
            ),
        },
    ]


def _continuation_reason(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and reason:
        return reason
    return exc.__class__.__name__


def stream_final_answer_with_recovery(
    answer_messages: list[dict[str, Any]],
    *,
    model: str,
    iter_stream: Callable[[list[dict[str, Any]], str], Iterator[str]],
    publish_chunk: Callable[[str], None],
    publish_event: Callable[[str, dict[str, Any]], None],
    should_stop: Callable[[], bool],
    adopt_buffer: Callable[[list[str]], None] | None = None,
    adopt_buffer_mode: Callable[[bool], None] | None = None,
    answer_phase: str = "final_answer",
    continuation_phase: str = "continuation",
) -> FinalAnswerRecoveryResult:
    """Stream every pass live, buffering only enough of a continuation to de-duplicate it.

    `adopt_buffer` receives the live buffer list for each continuation pass so a stop or a
    disconnect can still persist text that has not been published yet. `adopt_buffer_mode`
    reports when that buffer contains a full answer rewrite rather than a normal continuation.
    """
    raw_answer_chunks: list[str] = []
    continuation_count = 0
    max_continuations = get_final_answer_max_continuations()
    request_messages = answer_messages
    phase = answer_phase
    reasons: list[str] = []
    stalled = False
    restart_trimmed = False

    def publish_text(text: str) -> None:
        if not text:
            return
        raw_answer_chunks.append(text)
        publish_chunk(text)

    def result(error: LlmServiceError | None) -> FinalAnswerRecoveryResult:
        return FinalAnswerRecoveryResult(
            error,
            continuation_count,
            tuple(reasons),
            stalled,
            restart_trimmed,
        )

    def stalled_result() -> FinalAnswerRecoveryResult:
        nonlocal stalled
        stalled = True
        error = FinalAnswerContinuationStalledError()
        reasons.append(_continuation_reason(error))
        logger.warning(
            "Stopping continuation because the last pass produced no new text "
            "(model=%s, continuation=%s).",
            model,
            continuation_count,
        )
        return result(error)

    def flush_pass(state: _ContinuationPass) -> None:
        """Publish a buffered opening (or a spliced rewrite) exactly once."""
        nonlocal restart_trimmed
        if state.head_flushed:
            return
        state.head_flushed = True
        segment = state.text
        # バッファはジョブ側と共有しているため、配信したら必ず空にして二重保存を防ぐ。
        # The buffer is shared with the job, so clear it once published to avoid double save.
        state.buffer.clear()
        state.buffered_chars = 0
        if not segment:
            return

        existing = "".join(raw_answer_chunks)
        if state.full_buffer_mode:
            restart_trimmed = True
            spliced = splice_restarted_answer(existing, segment)
            if spliced is None:
                logger.warning(
                    "Discarded a continuation pass that restarted the answer and could not "
                    "be spliced back (model=%s, existing_chars=%s, pass_chars=%s).",
                    model,
                    len(existing),
                    len(segment),
                )
                return
            publish_text(spliced)
            return

        publish_text(strip_continuation_overlap(existing, segment))

    while True:
        state = _ContinuationPass()
        if continuation_count:
            if adopt_buffer is not None:
                adopt_buffer(state.buffer)
            if adopt_buffer_mode is not None:
                adopt_buffer_mode(False)
        chars_before_pass = len("".join(raw_answer_chunks))
        try:
            for chunk in iter_stream(request_messages, phase):
                if should_stop():
                    # 停止時の保存はジョブ側が共有バッファから行うため、ここでは配信しない。
                    # The job persists the shared buffer on stop, so do not publish here.
                    return result(None)
                if not chunk:
                    continue
                if not continuation_count or state.head_flushed:
                    publish_text(chunk)
                    continue

                state.buffer.append(chunk)
                state.buffered_chars += len(chunk)

                if not state.full_buffer_mode and looks_like_restarted_answer(
                    "".join(raw_answer_chunks),
                    state.text,
                ):
                    # 書き直しは全文が揃うまで配信しない。途中まで流すと本文が二重化する。
                    # A rewrite must not stream: publishing part of it duplicates the answer.
                    state.full_buffer_mode = True
                    if adopt_buffer_mode is not None:
                        adopt_buffer_mode(True)
                if state.full_buffer_mode:
                    continue
                if state.buffered_chars >= FINAL_ANSWER_CONTINUATION_OVERLAP_CHARS:
                    flush_pass(state)
        except LlmRateLimitError as exc:
            flush_pass(state)
            reasons.append(_continuation_reason(exc))
            if raw_answer_chunks:
                return result(exc)
            raise
        except LlmInputLimitError as exc:
            # 入力超過は継続で悪化する。ここで打ち切り、呼び出し側に入力圧縮を任せる。
            # Continuing an input overflow only makes it worse; stop and let the caller shrink.
            flush_pass(state)
            reasons.append(_continuation_reason(exc))
            if raw_answer_chunks:
                return result(exc)
            raise
        except (LlmOutputLimitError, LlmRetryableProviderError) as exc:
            flush_pass(state)
            reasons.append(_continuation_reason(exc))
            if continuation_count and len("".join(raw_answer_chunks)) <= chars_before_pass:
                # 1文字も進まない継続は、繰り返しても費用とレイテンシだけが増える。
                # A continuation that adds nothing only costs money and latency if repeated.
                return stalled_result()
            if continuation_count >= max_continuations or should_stop():
                return result(exc)
            continuation_count += 1
            logger.warning(
                "Continuing interrupted final answer "
                "(model=%s, continuation=%s/%s, reason=%s, output_chars=%s).",
                model,
                continuation_count,
                max_continuations,
                _continuation_reason(exc),
                len("".join(raw_answer_chunks)),
            )
            publish_event(
                "response_generation_started",
                {
                    "phase": "continuation",
                    "continuation": continuation_count,
                    "max_continuations": max_continuations,
                },
            )
            request_messages = build_final_answer_continuation_messages(
                answer_messages,
                "".join(raw_answer_chunks),
            )
            phase = continuation_phase
            continue
        except LlmServiceError as exc:
            flush_pass(state)
            reasons.append(_continuation_reason(exc))
            if raw_answer_chunks:
                return result(exc)
            raise

        flush_pass(state)
        if continuation_count and len("".join(raw_answer_chunks)) <= chars_before_pass:
            # 正常終了でも重複部分しか返さないモデルがある。成功扱いにすると、部分回答を
            # 継続できず、UIにも「ここまでで完了」と誤って伝わる。
            # A model can finish normally after returning only the repeated boundary. Treating
            # that as success loses the continuation affordance and falsely signals completion.
            return stalled_result()
        return result(None)
