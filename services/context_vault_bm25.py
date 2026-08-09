"""BM25-based near-duplicate filtering for personal-context candidates."""

from __future__ import annotations

import logging
from typing import Any

from services.bm25 import tokenize_bm25

logger = logging.getLogger(__name__)

# BM25 narrows the comparison set; token overlap then provides a stable,
# corpus-size-independent duplicate decision.
BM25_DUPLICATE_TOP_K = 5
BM25_DUPLICATE_TOKEN_OVERLAP = 0.55
BM25_DUPLICATE_MIN_SHARED_TOKENS = 2


def _document_text(document: dict[str, Any]) -> str:
    return f"{document.get('title', '')}\n{document.get('content', '')}"


def _has_duplicate(
    candidate: dict[str, Any],
    documents: list[dict[str, Any]],
) -> bool:
    same_type_documents = [
        document
        for document in documents
        if document.get("fact_type") == candidate.get("fact_type")
    ]
    if not same_type_documents:
        return False

    query_tokens = tokenize_bm25(_document_text(candidate))
    if not query_tokens:
        return False

    corpus_tokens = [
        tokenize_bm25(_document_text(document)) for document in same_type_documents
    ]
    try:
        from rank_bm25 import BM25L
    except ImportError:  # pragma: no cover - dependency is version-locked
        logger.warning(
            "rank_bm25 not installed; context candidate BM25 deduplication disabled."
        )
        return False

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
            return True
    return False


def filter_bm25_duplicates(
    candidates: list[dict[str, Any]],
    existing_documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop candidates near-duplicating existing documents or the same batch."""
    documents = [dict(document) for document in existing_documents]
    accepted: list[dict[str, Any]] = []
    for candidate in candidates:
        if _has_duplicate(candidate, documents):
            continue
        accepted.append(candidate)
        documents.append(candidate)
    return accepted
