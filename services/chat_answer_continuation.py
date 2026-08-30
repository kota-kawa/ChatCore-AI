"""Bounded recovery for interrupted user-facing answer streams."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from .llm import (
    LlmOutputLimitError,
    LlmRateLimitError,
    LlmRetryableProviderError,
    LlmServiceError,
)

logger = logging.getLogger(__name__)

DEFAULT_FINAL_ANSWER_MAX_CONTINUATIONS = 2
FINAL_ANSWER_CONTINUATION_OVERLAP_CHARS = 2048


@dataclass(frozen=True)
class FinalAnswerRecoveryResult:
    error: LlmServiceError | None
    continuation_count: int


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


def stream_final_answer_with_recovery(
    answer_messages: list[dict[str, Any]],
    *,
    model: str,
    iter_stream: Callable[[list[dict[str, Any]], str], Iterator[str]],
    publish_chunk: Callable[[str], None],
    publish_event: Callable[[str, dict[str, Any]], None],
    should_stop: Callable[[], bool],
) -> FinalAnswerRecoveryResult:
    """Stream the first pass live and buffer only bounded continuation passes."""
    raw_answer_chunks: list[str] = []
    continuation_count = 0
    max_continuations = get_final_answer_max_continuations()
    request_messages = answer_messages
    phase = "final_answer"

    def publish_text(text: str) -> None:
        if not text:
            return
        raw_answer_chunks.append(text)
        publish_chunk(text)

    def publish_buffered(segment_chunks: list[str]) -> None:
        continuation = strip_continuation_overlap(
            "".join(raw_answer_chunks),
            "".join(segment_chunks),
        )
        publish_text(continuation)

    while True:
        buffered_continuation: list[str] = []
        try:
            for chunk in iter_stream(request_messages, phase):
                if should_stop():
                    return FinalAnswerRecoveryResult(None, continuation_count)
                if not chunk:
                    continue
                if continuation_count:
                    buffered_continuation.append(chunk)
                else:
                    publish_text(chunk)
        except LlmRateLimitError as exc:
            publish_buffered(buffered_continuation)
            if raw_answer_chunks:
                return FinalAnswerRecoveryResult(exc, continuation_count)
            raise
        except (LlmOutputLimitError, LlmRetryableProviderError) as exc:
            publish_buffered(buffered_continuation)
            if continuation_count >= max_continuations or should_stop():
                return FinalAnswerRecoveryResult(exc, continuation_count)
            continuation_count += 1
            logger.warning(
                "Continuing interrupted final answer "
                "(model=%s, continuation=%s/%s, reason=%s, output_chars=%s).",
                model,
                continuation_count,
                max_continuations,
                getattr(exc, "reason", exc.__class__.__name__),
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
            phase = "continuation"
            continue
        except LlmServiceError as exc:
            publish_buffered(buffered_continuation)
            if raw_answer_chunks:
                return FinalAnswerRecoveryResult(exc, continuation_count)
            raise

        publish_buffered(buffered_continuation)
        return FinalAnswerRecoveryResult(None, continuation_count)
