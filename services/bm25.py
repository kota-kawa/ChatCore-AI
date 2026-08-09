"""Shared text normalization and tokenization for BM25 search."""

from __future__ import annotations

import re
import unicodedata


def tokenize_bm25(text: str) -> list[str]:
    """Tokenize ASCII words and CJK character bigrams/unigrams for BM25."""
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    tokens = re.findall(r"[a-z0-9]+", normalized)
    cjk_chars = [
        char
        for char in normalized
        if unicodedata.category(char) in ("Lo", "Ll") and ord(char) > 0x2E7F
    ]
    cjk_text = "".join(cjk_chars)
    tokens.extend(cjk_text[index : index + 2] for index in range(len(cjk_text) - 1))
    tokens.extend(cjk_chars)
    return tokens
