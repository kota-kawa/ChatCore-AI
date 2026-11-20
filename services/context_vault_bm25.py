# 個人コンテキスト候補の類似重複をBM25で絞り込む。
"""BM25-based near-duplicate filtering for personal-context candidates."""

from __future__ import annotations

import logging
from typing import Any

from services.bm25 import tokenize_bm25

logger = logging.getLogger(__name__)

# BM25で比較候補を絞り、語の重なりでコーパス規模に依存しない重複判定を行う。
# BM25 narrows the comparison set; token overlap then provides a stable,
# corpus-size-independent duplicate decision.
BM25_DUPLICATE_TOP_K = 5
BM25_DUPLICATE_TOKEN_OVERLAP = 0.55
BM25_DUPLICATE_MIN_SHARED_TOKENS = 2


def _document_text(document: dict[str, Any]) -> str:
    return f"{document.get('title', '')}\n{document.get('content', '')}"


def _find_duplicate(
    candidate: dict[str, Any],
    documents: list[dict[str, Any]],
) -> dict[str, Any] | None:
    same_type_documents = [
        document
        for document in documents
        if document.get("fact_type") == candidate.get("fact_type")
    ]
    if not same_type_documents:
        return None

    query_tokens = tokenize_bm25(_document_text(candidate))
    if not query_tokens:
        return None

    corpus_tokens = [
        tokenize_bm25(_document_text(document)) for document in same_type_documents
    ]
    try:
        from rank_bm25 import BM25L
    except ImportError:  # pragma: no cover - dependency is version-locked
        logger.warning(
            "rank_bm25 not installed; context candidate BM25 deduplication disabled."
        )
        return None

    scores = BM25L(corpus_tokens).get_scores(query_tokens).tolist()
    ranked_indexes = sorted(
        range(len(scores)),
        key=lambda index: scores[index],
        reverse=True,
    )[:BM25_DUPLICATE_TOP_K]
    query_set = set(query_tokens)
    for index in ranked_indexes:
        if scores[index] <= 0:
            continue
        document_set = set(corpus_tokens[index])
        shared_count = len(query_set & document_set)
        if shared_count < BM25_DUPLICATE_MIN_SHARED_TOKENS:
            continue
        denominator = min(len(query_set), len(document_set))
        if denominator and shared_count / denominator >= BM25_DUPLICATE_TOKEN_OVERLAP:
            return same_type_documents[index]
    return None


def find_bm25_duplicates(
    candidates: list[dict[str, Any]],
    existing_documents: list[dict[str, Any]],
) -> list[dict[str, Any] | None]:
    # 各候補が類似重複している相手の文書を、候補と同じ並びで返す。重複していない候補は None。
    # 相手は既存文書（渡した辞書のコピー）か、同一バッチで先に残った候補。
    """For each candidate, return the document it near-duplicates, or None when it is unique.

    The match is a copy of the existing document passed in, or an earlier candidate of the same batch.
    """
    documents = [dict(document) for document in existing_documents]
    matches: list[dict[str, Any] | None] = []
    for candidate in candidates:
        match = _find_duplicate(candidate, documents)
        matches.append(match)
        if match is None:
            documents.append(candidate)
    return matches

