"""Embedding generation for memo and personal-context semantic search.

One provider, one place. Everything that stores or queries an embedding vector goes
through :func:`generate_embedding`, so the model and its dimension count cannot drift
apart from the ``vector(768)`` columns the vectors are written into.

Failures are latched rather than swallowed one call at a time: a misconfigured model
name used to keep every memo search paying for a doomed round-trip while silently
degrading to substring matching, with nothing surfaced to operators.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from .llm import openai_client

logger = logging.getLogger(__name__)

# OpenAI の text-embedding-3-small は `dimensions` で短縮出力に対応する。768 を指定して
# memo_entries / context_facts の vector(768) 列にそのまま格納する（列変更不要）。
# text-embedding-3-small supports shortened output through `dimensions`. Requesting 768
# keeps the vectors compatible with the existing vector(768) columns, so no migration.
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = 768
# モデルの入力上限は 8192 トークン。日本語は1文字が1トークンを超えることがあるため、
# 文字数で切る側は余裕を持たせて上限超過の 400 を避ける。
# The model accepts 8192 input tokens. Japanese can exceed one token per character, so the
# character-side cap keeps a margin rather than riding the limit.
EMBEDDING_MAX_INPUT_CHARS = 6000

# pgvector のコサイン距離（`<=>`、0〜2）の採用上限。ANN 検索は上限が無いと、無関係な
# 質問にも必ず LIMIT 件を返し、モデルが無関係なメモを根拠として引用してしまう。
# 実データで調整できるよう環境変数で上書きできる。
# Cosine-distance ceiling for pgvector (`<=>`, 0-2). Without it an ANN search always returns
# LIMIT rows, even for an unrelated question, and the model cites an unrelated memo as
# evidence. Overridable so it can be tuned against real data.
SEMANTIC_MAX_DISTANCE = 0.75


def get_semantic_max_distance() -> float:
    """Return the cosine-distance ceiling for semantic search."""
    raw = os.environ.get("SEMANTIC_MAX_DISTANCE")
    if raw is None:
        return SEMANTIC_MAX_DISTANCE
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return SEMANTIC_MAX_DISTANCE
    return value if 0.0 < value <= 2.0 else SEMANTIC_MAX_DISTANCE


# 連続失敗がこの回数に達したら、クールダウンの間は呼び出し自体を止める。
# After this many consecutive failures the provider is left alone for the cooldown.
EMBEDDING_FAILURE_THRESHOLD = 3
EMBEDDING_FAILURE_COOLDOWN_SECONDS = 300.0

_state_lock = threading.Lock()
_consecutive_failures = 0
_disabled_until = 0.0


def reset_embedding_failure_state() -> None:
    """Clear the failure latch (used by tests and after a configuration change)."""
    global _consecutive_failures, _disabled_until
    with _state_lock:
        _consecutive_failures = 0
        _disabled_until = 0.0


def _record_success() -> None:
    global _consecutive_failures, _disabled_until
    with _state_lock:
        _consecutive_failures = 0
        _disabled_until = 0.0


def _record_failure() -> None:
    global _consecutive_failures, _disabled_until
    with _state_lock:
        _consecutive_failures += 1
        if _consecutive_failures < EMBEDDING_FAILURE_THRESHOLD:
            return
        _disabled_until = time.monotonic() + EMBEDDING_FAILURE_COOLDOWN_SECONDS
        failures = _consecutive_failures
    logger.error(
        "Embedding generation failed %s times in a row; pausing embeddings for %.0fs. "
        "Semantic memo and My Context search are degraded until this recovers.",
        failures,
        EMBEDDING_FAILURE_COOLDOWN_SECONDS,
    )


def embeddings_available() -> bool:
    """Return True when embeddings are configured and not in a failure cooldown."""
    if openai_client is None:
        return False
    with _state_lock:
        return time.monotonic() >= _disabled_until


def get_embedding_health() -> dict[str, Any]:
    """Report the embedding provider state for the readiness endpoint."""
    with _state_lock:
        cooling_down = time.monotonic() < _disabled_until
        failures = _consecutive_failures
    if openai_client is None:
        status = "disabled"
    elif cooling_down:
        status = "error"
    elif failures:
        status = "degraded"
    else:
        status = "ok"
    return {
        "status": status,
        "required": False,
        "model": EMBEDDING_MODEL,
        "dimensions": EMBEDDING_DIMENSIONS,
        "consecutive_failures": failures,
    }


def generate_embedding(text: str) -> list[float] | None:
    """Generate one dense embedding, or None when embeddings are unavailable."""
    if not embeddings_available():
        return None

    normalized = text.strip()[:EMBEDDING_MAX_INPUT_CHARS]
    if not normalized:
        return None

    try:
        response = openai_client.embeddings.create(  # type: ignore[union-attr]
            model=EMBEDDING_MODEL,
            input=normalized,
            dimensions=EMBEDDING_DIMENSIONS,
        )
        embedding = [float(value) for value in response.data[0].embedding]
    except Exception:
        logger.warning("Embedding generation failed.", exc_info=True)
        _record_failure()
        return None

    if len(embedding) != EMBEDDING_DIMENSIONS:
        # 次元がずれたベクトルを保存すると pgvector の挿入時に落ちるため、ここで捨てる。
        # Storing a mismatched vector fails at pgvector insert time, so drop it here.
        logger.error(
            "Embedding model %s returned %s dimensions; expected %s.",
            EMBEDDING_MODEL,
            len(embedding),
            EMBEDDING_DIMENSIONS,
        )
        _record_failure()
        return None

    _record_success()
    return embedding
