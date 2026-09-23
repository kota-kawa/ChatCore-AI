"""Read token usage from provider responses and hand it to the usage meter.

プロバイダごとに使用量の形が違うため、ここで共通の (入力, キャッシュ入力, 出力) に
揃えます。ストリームが途中で閉じられて使用量が届かなかった場合も課金はされているので、
入力と出力の文字数から見積もって記録します（上限が甘くならない安全側）。
Each provider reports usage in its own shape; this module normalizes it to
(input, cached input, output). A stream closed before its usage arrived is still billed,
so it is recorded from an estimate of the input and output text, erring on the side of
counting.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from services.usage_metering import record_token_usage

logger = logging.getLogger(__name__)


def _field(source: Any, name: str) -> Any:
    if source is None:
        return None
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _count(source: Any, name: str) -> int:
    try:
        return max(int(_field(source, name) or 0), 0)
    except (TypeError, ValueError):
        return 0


def record_chat_completion_usage(model_name: str, usage: Any) -> bool:
    """Record Chat Completions usage (OpenAI and Groq). Returns False when absent."""

    if usage is None:
        return False
    record_token_usage(
        model_name,
        input_tokens=_count(usage, "prompt_tokens"),
        cached_input_tokens=_count(_field(usage, "prompt_tokens_details"), "cached_tokens"),
        cache_write_input_tokens=_count(_field(usage, "prompt_tokens_details"), "cache_write_tokens"),
        output_tokens=_count(usage, "completion_tokens"),
    )
    return True


def record_responses_usage(model_name: str, usage: Any) -> bool:
    """Record OpenAI Responses API usage. Returns False when absent."""

    if usage is None:
        return False
    record_token_usage(
        model_name,
        input_tokens=_count(usage, "input_tokens"),
        cached_input_tokens=_count(_field(usage, "input_tokens_details"), "cached_tokens"),
        cache_write_input_tokens=_count(_field(usage, "input_tokens_details"), "cache_write_tokens"),
        output_tokens=_count(usage, "output_tokens"),
    )
    return True


def record_claude_usage(model_name: str, usage: Any) -> bool:
    """Record Anthropic usage. Returns False when absent.

    Anthropic は入力をキャッシュ読み出し・キャッシュ書き込み・それ以外に分けて返すため、
    合計して入力とし、書き込み分は割増の単価で数える。
    Anthropic splits input into cache reads, cache writes and the rest; they are summed, and
    the written portion is billed at the cache-write premium.
    """

    if usage is None:
        return False
    cache_read = _count(usage, "cache_read_input_tokens")
    cache_write = _count(usage, "cache_creation_input_tokens")
    record_token_usage(
        model_name,
        input_tokens=_count(usage, "input_tokens") + cache_write + cache_read,
        cached_input_tokens=cache_read,
        cache_write_input_tokens=cache_write,
        output_tokens=_count(usage, "output_tokens"),
    )
    return True


def record_embedding_usage(model_name: str, usage: Any) -> bool:
    """Record embeddings usage, which is billed on input only."""

    if usage is None:
        return False
    record_token_usage(model_name, input_tokens=_count(usage, "prompt_tokens"), output_tokens=0)
    return True


def record_estimated_usage(
    model_name: str,
    messages: Sequence[Mapping[str, Any]] | None,
    output_text: str,
    *,
    tools: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Record a call whose provider usage never arrived, from a text-based estimate."""

    # 見積もり関数は Web 検索経由で services.llm を読み込むため、ここで遅延 import する。
    # The estimators import services.llm through web search, so import them lazily here.
    from services.chat_context import estimate_token_count
    from services.llm_context_budget import estimate_request_tokens

    try:
        input_tokens = estimate_request_tokens(messages, tools)
    except Exception:
        logger.debug("Could not estimate request tokens for usage metering.", exc_info=True)
        input_tokens = 0
    record_token_usage(
        model_name,
        input_tokens=input_tokens,
        output_tokens=estimate_token_count(output_text) if output_text else 0,
    )
