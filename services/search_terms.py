"""Query-term splitting and LIKE escaping shared by keyword search paths.

Memo and My Context keyword search used to match the whole query as one substring, so a
multi-word query only ever matched a memo containing that exact string end to end.
Splitting the query into terms and requiring each one lets "沖縄 旅行 予算" match a memo
that contains all three words in any order.
"""

from __future__ import annotations

import re

# 検索語として扱う区切り。空白（全角含む）と一般的な句読点で切る。
# 助詞での分割は行わない: 形態素解析なしでは誤分割が多く、呼び出し側が渡す
# キーワード列（空白区切り）を正しく扱うことのほうが重要。
# Separators for search terms: whitespace (including full-width) and common punctuation.
# Particles are deliberately not split on — without a morphological analyzer that mangles
# more queries than it helps, and callers already pass space-separated keywords.
_TERM_SEPARATOR_PATTERN = re.compile(r"[\s、。，．,.;:!?！？「」『』（）()\[\]【】〈〉<>\"'|/\\]+")

# 語数の上限。1語につき ILIKE 条件が2つ増えるため、際限なく増やさない。
# Each term adds two ILIKE conditions, so cap how many a single query may contribute.
MAX_SEARCH_TERMS = 8


def split_search_terms(query: str, *, limit: int = MAX_SEARCH_TERMS) -> list[str]:
    """Split a query into distinct search terms, preserving the caller's order."""
    terms: list[str] = []
    for raw_term in _TERM_SEPARATOR_PATTERN.split(str(query or "")):
        term = raw_term.strip()
        if not term or term in terms:
            continue
        terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def escape_like_term(term: str) -> str:
    """Escape LIKE wildcards so a literal % or _ cannot widen the match."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_like_pattern(term: str) -> str:
    """Build the ``%term%`` pattern for a single search term."""
    return f"%{escape_like_term(term)}%"
