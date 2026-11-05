"""BM25 検索で共有するテキストの正規化とトークン化。

Shared text normalization and tokenization for BM25 search.
"""

from __future__ import annotations

import re
import unicodedata


def tokenize_bm25(text: str) -> list[str]:
    """BM25 用に、ASCII の単語と CJK 文字の bigram・unigram へ分割する。

    Tokenize ASCII words and CJK character bigrams/unigrams for BM25.
    """
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    tokens = re.findall(r"[a-z0-9]+", normalized)
    # 空白区切りのない日本語などは単語境界が取れないため、文字単位と2文字連続の両方を索引語にする。
    # Text without spaces (such as Japanese) has no word boundaries, so index both single characters and adjacent pairs.
    cjk_chars = [
        char
        for char in normalized
        if unicodedata.category(char) in ("Lo", "Ll") and ord(char) > 0x2E7F
    ]
    cjk_text = "".join(cjk_chars)
    tokens.extend(cjk_text[index : index + 2] for index in range(len(cjk_text) - 1))
    tokens.extend(cjk_chars)
    return tokens
