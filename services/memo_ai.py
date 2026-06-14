"""AI-powered memo assistance: title suggestion and semantic search via embeddings."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import numpy as np

from .llm import GROQ_MODEL, LlmProviderError, groq_client, get_llm_response

MEMO_SUGGEST_MODEL = GROQ_MODEL
EMBEDDING_MODEL = "nomic-embed-text-v1_5"
EMBEDDING_MAX_INPUT_CHARS = 8000
EMBEDDING_RESPONSE_SAMPLE_CHARS = 2000
SUGGEST_RESPONSE_SAMPLE_CHARS = 1500
SUGGEST_TITLE_MAX_LEN = 255

logger = logging.getLogger(__name__)


# 日本語: extract json に関する処理の入口です。
# English: Entry point for logic related to extract json.
def _extract_json(raw: str) -> dict[str, Any]:
    """Strip Markdown code fences and parse the first JSON object found."""
    cleaned = raw.strip()
    # Remove ```json ... ``` or ``` ... ```
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()
    # Find first {...}
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


# 日本語: fallback suggest に関する処理の入口です。
# English: Entry point for logic related to fallback suggest.
def _fallback_suggest(ai_response: str) -> dict[str, Any]:
    """Return a minimal suggestion from the first non-empty line of the AI response."""
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for line in (ai_response or "").splitlines():
        cleaned = re.sub(r"^#+\s*", "", line).strip()
        if cleaned:
            return {"title": cleaned[:100]}
    return {"title": ""}


# 日本語: suggest title に関する処理の入口です。
# English: Entry point for logic related to suggest title.
def suggest_title(ai_response: str) -> dict[str, Any]:
    """Use LLM to suggest a title for a memo.

    Returns a dict with key ``title`` (str).
    Falls back to heuristics when the LLM is unavailable or returns malformed JSON.
    """
    response_sample = (ai_response or "").strip()[:SUGGEST_RESPONSE_SAMPLE_CHARS]

    messages = [
        {
            "role": "system",
            "content": (
                "あなたはメモ整理アシスタントです。"
                "ユーザーが保存したいメモの内容から、適切なタイトルを提案してください。"
                "必ず JSON オブジェクトのみを返してください。Markdown、コードフェンス、前置きは使わないでください。"
                '形式: {"title": "タイトル（30文字以内）"}'
            ),
        },
        {
            "role": "user",
            "content": (
                f"【メモ本文】\n{response_sample}\n\n"
                "このメモに適切なタイトル（30文字以内）を提案してください。"
                '必ずJSONのみで回答: {"title": "..."}'
            ),
        },
    ]

    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        raw = get_llm_response(messages, MEMO_SUGGEST_MODEL)
        if not raw:
            return _fallback_suggest(ai_response)

        data = _extract_json(raw)
        title = str(data.get("title") or "").strip()[:SUGGEST_TITLE_MAX_LEN]

        return {"title": title}

    except LlmProviderError:
        logger.warning("LLM unavailable for memo suggestion; using fallback.")
        return _fallback_suggest(ai_response)
    except Exception:
        logger.warning("Memo AI suggestion failed; using fallback.", exc_info=True)
        return _fallback_suggest(ai_response)


# 日本語: embeddings available に関する処理の入口です。
# English: Entry point for logic related to embeddings available.
def embeddings_available() -> bool:
    """Return True when the Groq client is configured and can generate embeddings."""
    return groq_client is not None


# 日本語: generate embedding の生成処理を担当します。
# English: Handle generating for generate embedding.
def generate_embedding(text: str) -> list[float] | None:
    """Generate a dense embedding vector for the given text via Groq.

    Returns ``None`` when embeddings are unavailable or the call fails.
    """
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not embeddings_available():
        return None

    normalized = text.strip()[:EMBEDDING_MAX_INPUT_CHARS]
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not normalized:
        return None

    try:
        response = groq_client.embeddings.create(  # type: ignore[union-attr]
            model=EMBEDDING_MODEL,
            input=normalized,
        )
        return response.data[0].embedding
    except Exception:
        logger.warning("Embedding generation failed.", exc_info=True)
        return None


# 日本語: build memo embedding text の組み立て処理を担当します。
# English: Handle building for build memo embedding text.
def build_memo_embedding_text(title: str, ai_response: str) -> str:
    """Combine memo fields into a single string optimised for embedding."""
    parts: list[str] = []
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if title:
        parts.append(f"タイトル: {title}")
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if ai_response:
        parts.append(ai_response[:EMBEDDING_RESPONSE_SAMPLE_CHARS])
    return "\n".join(parts)


# 日本語: cosine similarity に関する処理の入口です。
# English: Entry point for logic related to cosine similarity.
def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    norm_a = float(np.linalg.norm(va))
    norm_b = float(np.linalg.norm(vb))
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


# 日本語: rank memos by semantic similarity に関する処理の入口です。
# English: Entry point for logic related to rank memos by semantic similarity.
def rank_memos_by_semantic_similarity(
    query_embedding: list[float],
    memos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return *memos* sorted by descending cosine similarity to *query_embedding*.

    Memos without an embedding are placed at the end with score 0.
    """
    scored: list[tuple[float, dict[str, Any]]] = []
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for memo in memos:
        emb_raw = memo.get("embedding")
        score = 0.0
        if emb_raw:
            try:
                emb: list[float] = json.loads(emb_raw) if isinstance(emb_raw, str) else emb_raw
                score = _cosine_similarity(query_embedding, emb)
            except Exception:
                pass
        scored.append((score, memo))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [memo for _, memo in scored]
