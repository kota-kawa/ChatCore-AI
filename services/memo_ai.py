# AIによるメモ支援機能：埋め込みベクトルを用いたセマンティック検索と、タイトルの提案機能を提供します。
# AI-powered memo assistance: title suggestion and semantic search via embeddings.

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


# テキストからJSON部分（Markdownコードフェンス等を含む）を抽出し、辞書オブジェクトに変換します。
# Extract and parse JSON from raw text, stripping markdown code fences.
def _extract_json(raw: str) -> dict[str, Any]:
    # テキストからMarkdownのコードフェンスを除去し、最初に見つかったJSONオブジェクトをパースします。
    # Strip Markdown code fences and parse the first JSON object found.
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


# AIからの応答テキストの最初の空でない行から、簡易的なタイトルを抽出するフォールバック処理。
# Extract a simple fallback title from the first non-empty line of AI response.
def _fallback_suggest(ai_response: str) -> dict[str, Any]:
    # AI応答の最初の空行以外の行から、最小限のタイトル案を生成します。
    # Return a minimal suggestion from the first non-empty line of the AI response.
    """Return a minimal suggestion from the first non-empty line of the AI response."""
    for line in (ai_response or "").splitlines():
        cleaned = re.sub(r"^#+\s*", "", line).strip()
        if cleaned:
            return {"title": cleaned[:100]}
    return {"title": ""}


# メモの本文テキストをもとに、LLMを呼び出して適切なタイトルを提案させます。不全時はヒューリスティクスにフォールバックします。
# Call LLM to suggest a concise title for a memo, falling back to heuristics on failure.
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


# 埋め込みベクトルの生成機能（Groqクライアント）が有効かどうかを返します。
# Return whether the embedding generation capability is configured and available.
def embeddings_available() -> bool:
    # 埋め込みベクトルの生成機能（Groqクライアント）が有効かどうかを返します。
    # Return True when the Groq client is configured and can generate embeddings.
    """Return True when the Groq client is configured and can generate embeddings."""
    return groq_client is not None


# 与えられたテキストから、Groq APIを使用して埋め込みベクトル(1次元配列)を生成します。
# Generate a dense embedding vector for the text using the Groq API.
def generate_embedding(text: str) -> list[float] | None:
    # 与えられたテキストから、Groq APIを使用して埋め込みベクトル(1次元配列)を生成します。
    # Generate a dense embedding vector for the text using the Groq API.
    """Generate a dense embedding vector for the given text via Groq."""
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


# メモのタイトルと本文を、埋め込みベクトル生成に最適な形式に結合します。
# Combine the title and body content into a format optimized for embedding.
def build_memo_embedding_text(title: str, ai_response: str) -> str:
    # メモのタイトルと本文を、埋め込みベクトル生成に最適な形式に結合します。
    # Combine the title and body content into a format optimized for embedding.
    """Combine memo fields into a single string optimised for embedding."""
    parts: list[str] = []
    if title:
        parts.append(f"タイトル: {title}")
    if ai_response:
        parts.append(ai_response[:EMBEDDING_RESPONSE_SAMPLE_CHARS])
    return "\n".join(parts)


# 2つのベクトルのコサイン類似度を算出します。
# Calculate the cosine similarity score between two vectors.
def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    norm_a = float(np.linalg.norm(va))
    norm_b = float(np.linalg.norm(vb))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


# クエリの埋め込みベクトルと各メモの類似度を計算し、類似度の高い順にソートしたメモ一覧を返します。
# Sort the list of memos in descending order of similarity to the query embedding.
def rank_memos_by_semantic_similarity(
    query_embedding: list[float],
    memos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # クエリの埋め込みベクトルと各メモの類似度を計算し、類似度の高い順にソートしたメモ一覧を返します。
    # Sort the list of memos in descending order of similarity to the query embedding.
    """Return *memos* sorted by descending cosine similarity to *query_embedding*."""
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
