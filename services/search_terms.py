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
# `/` と `\` は URL やパスの一部として語の中に現れるため、区切りには含めない。
# `/` and `\` are left out: they appear inside terms such as URLs and file paths.
_TERM_SEPARATOR_PATTERN = re.compile(r"[\s、。，．,.;:!?！？「」『』（）()\[\]【】〈〉<>\"'|]+")

# 語数の上限。1語につき ILIKE 条件が増える（通常は列ごとに1つで2つ、メモ検索はひらがな・カタカナの
# 綴りも並べるため最大6つ）ので、際限なく増やさない。
# Each term adds ILIKE conditions (one per column, so two; memo search also spells the term in
# hiragana and katakana, so up to six), so cap how many a single query may contribute.
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


# ひらがな U+3041-3096 とカタカナ U+30A1-30F6 は 0x60 ずれで1対1に対応する（ゝゞ・ヽヾ も同様）。
# ヷヸヹヺ（U+30F7-30FA）には対応するひらがながないので変換しない。
# Hiragana U+3041-3096 and katakana U+30A1-30F6 map one to one at a 0x60 offset (as do the
# iteration marks ゝゞ and ヽヾ); ヷヸヹヺ (U+30F7-30FA) have no hiragana form and are left alone.
_KANA_OFFSET = 0x60
_KANA_PAIRS = [(code, code + _KANA_OFFSET) for code in (*range(0x3041, 0x3097), 0x309D, 0x309E)]
_TO_KATAKANA = dict(_KANA_PAIRS)
_TO_HIRAGANA = {kata: hira for hira, kata in _KANA_PAIRS}


def kana_variants(term: str) -> list[str]:
    """Return the term plus its all-hiragana and all-katakana spellings, without duplicates.

    ひらがなの「ぱすぽーと」とカタカナの「パスポート」を同じ語として当てるため、列を正規化せず
    クエリ側だけで両方の綴りを作り、呼び出し側が OR で当てる。列に関数をかけると
    pg_trgm の GIN 索引（ILIKE）が使えなくなるので、この形にしている。
    Lets "ぱすぽーと" match "パスポート" and vice versa by spelling the query both ways and OR-ing
    them, rather than normalizing the column: wrapping a column in a function would stop the
    pg_trgm GIN indexes from serving ILIKE. Full-width and half-width katakana are not unified.
    """
    variants = [term]
    for converted in (term.translate(_TO_HIRAGANA), term.translate(_TO_KATAKANA)):
        if converted not in variants:
            variants.append(converted)
    return variants


def escape_like_term(term: str) -> str:
    """Escape LIKE wildcards so a literal % or _ cannot widen the match."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_like_pattern(term: str) -> str:
    """Build the ``%term%`` pattern for a single search term."""
    return f"%{escape_like_term(term)}%"
