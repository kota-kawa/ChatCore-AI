"""AI-powered memo assistance: title/tag suggestion and semantic search via embeddings."""

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
SUGGEST_INPUT_SAMPLE_CHARS = 500
SUGGEST_TITLE_MAX_LEN = 255
SUGGEST_TAGS_MAX_LEN = 255

logger = logging.getLogger(__name__)


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
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def _fallback_suggest(ai_response: str) -> dict[str, Any]:
    """Return a minimal suggestion from the first non-empty line of the AI response."""
    for line in (ai_response or "").splitlines():
        cleaned = re.sub(r"^#+\s*", "", line).strip()
        if cleaned:
            return {"title": cleaned[:100], "tags": ""}
    return {"title": "", "tags": ""}


def suggest_title_and_tags(input_content: str, ai_response: str) -> dict[str, Any]:
    """Use LLM to suggest a title and space-separated tags for a memo.

    Returns a dict with keys ``title`` (str) and ``tags`` (str).
    Falls back to heuristics when the LLM is unavailable or returns malformed JSON.
    """
    content_sample = (input_content or "").strip()[:SUGGEST_INPUT_SAMPLE_CHARS]
    response_sample = (ai_response or "").strip()[:SUGGEST_RESPONSE_SAMPLE_CHARS]

    messages = [
        {
            "role": "system",
            "content": (
                "あなたはメモ整理アシスタントです。"
                "ユーザーが保存したいメモの内容から、適切なタイトルとタグを提案してください。"
                "必ず JSON オブジェクトのみを返してください。Markdown、コードフェンス、前置きは使わないでください。"
                '形式: {"title": "タイトル（30文字以内）", "tags": ["タグ1", "タグ2", "タグ3"]}'
            ),
        },
        {
            "role": "user",
            "content": (
                f"【入力内容】\n{content_sample}\n\n"
                f"【AIの回答】\n{response_sample}\n\n"
                "このメモに適切なタイトル（30文字以内）と3〜5個のタグを提案してください。"
                '必ずJSONのみで回答: {"title": "...", "tags": ["...", "..."]}'
            ),
        },
    ]

    try:
        raw = get_llm_response(messages, MEMO_SUGGEST_MODEL)
        if not raw:
            return _fallback_suggest(ai_response)

        data = _extract_json(raw)
        title = str(data.get("title") or "").strip()[:SUGGEST_TITLE_MAX_LEN]

        tags_raw = data.get("tags", [])
        if isinstance(tags_raw, list):
            tags = " ".join(
                str(t).strip() for t in tags_raw if str(t).strip()
            )[:SUGGEST_TAGS_MAX_LEN]
        else:
            tags = str(tags_raw).strip()[:SUGGEST_TAGS_MAX_LEN]

        return {"title": title, "tags": tags}

    except LlmProviderError:
        logger.warning("LLM unavailable for memo suggestion; using fallback.")
        return _fallback_suggest(ai_response)
    except Exception:
        logger.warning("Memo AI suggestion failed; using fallback.", exc_info=True)
        return _fallback_suggest(ai_response)


def embeddings_available() -> bool:
    """Return True when the Groq client is configured and can generate embeddings."""
    return groq_client is not None


def generate_embedding(text: str) -> list[float] | None:
    """Generate a dense embedding vector for the given text via Groq.

    Returns ``None`` when embeddings are unavailable or the call fails.
    """
    if not embeddings_available():
        return None

    normalized = text.strip()[:EMBEDDING_MAX_INPUT_CHARS]
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


def build_memo_embedding_text(title: str, tags: str, ai_response: str) -> str:
    """Combine memo fields into a single string optimised for embedding."""
    parts: list[str] = []
    if title:
        parts.append(f"タイトル: {title}")
    if tags:
        parts.append(f"タグ: {tags}")
    if ai_response:
        parts.append(ai_response[:EMBEDDING_RESPONSE_SAMPLE_CHARS])
    return "\n".join(parts)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    norm_a = float(np.linalg.norm(va))
    norm_b = float(np.linalg.norm(vb))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def rank_memos_by_semantic_similarity(
    query_embedding: list[float],
    memos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return *memos* sorted by descending cosine similarity to *query_embedding*.

    Memos without an embedding are placed at the end with score 0.
    """
    scored: list[tuple[float, dict[str, Any]]] = []
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
