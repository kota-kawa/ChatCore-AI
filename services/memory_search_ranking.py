"""記憶（context_facts）の検索の順位づけ。語の一致（BM25）と意味の近さ（埋め込みのコサイン距離）を順位の融合（RRF）で合わせる（ADR 0025）。

DB にも LLM にも触れない純粋な計算で、同じ入力（行、検索語、現在時刻）なら必ず同じ順位になる。
重要度・最後に話題に出た日の新しさ・本人の確認は、融合した順位を大きくは覆さない小さな加点としてだけ足す。

Ranking for memory (context_facts) search, per ADR 0025: lexical match (BM25) and semantic closeness
(cosine distance between embeddings) are merged by Reciprocal Rank Fusion. This is pure computation with
no DB or LLM access, and the same input (rows, query, current time) always yields the same order.
Importance, how recently a fact was mentioned and owner confirmation are only small boosts that cannot
overturn the fused ranking by much.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from services.bm25 import tokenize_bm25
from services.embeddings import get_semantic_max_distance

# 1 回の検索で返す記憶の最大件数。
# The most memories one search returns.
MEMORY_SEARCH_RESULT_LIMIT = 5

# BM25 の定数。Robertson らの標準的な値で、1 件が最大 2000 文字の短い文書が最大 200 件という規模でも偏らない。
# BM25 constants: the standard values from Robertson et al., balanced for short documents
# (at most 2000 characters each) in a corpus of at most 200.
BM25_K1 = 1.5
BM25_B = 0.75

# RRF の定数 k。Cormack らが提案した 60 を使う。上位の順位の差が 1/(k+rank) の差として小さく出るので、順位の融合では
# 語の一致と意味の近さのどちらか一方の 1 位が他方を押しのけない。
# The RRF constant k: 60 as proposed by Cormack et al. Rank differences at the top come out as small 1/(k+rank) steps, so no single
# list's first place can push aside the other list's evidence.
RRF_K = 60

# 加点の上限。RRF の 1 位と 2 位の差は 1/60 - 1/61 ≒ 0.00027、10 位前後の隣り合う順位の差は 0.0002 前後で、
# 全部の加点が満点でも 0.0008（上位の順位で 3 つ分ほど）に収まるようにする。片方の一覧だけに出る記憶の 1 位は
# 1/61 ≒ 0.0164 で、満点の加点を足しても 0.0172。両方の一覧で 20 位以内に入る記憶は 2/(60+20) = 0.025 以上なので、
# 加点で「片方だけで当たった記憶」が「両方で当たった記憶」を追い抜くことはない。
# Boost ceilings. At the top, adjacent RRF ranks differ by about 0.00027 (1/60 - 1/61) and around rank 10 by about
# 0.0002, so all boosts together cap at 0.0008 (roughly three places near the top). The best memory found by one
# list scores 1/61 = 0.0164 (0.0172 with every boost at its maximum), while a memory within the top 20 of both
# lists scores at least 2/(60+20) = 0.025, so a boost never lifts a one-list match above a two-list match.
IMPORTANCE_BOOST_MAX = 0.0004
RECENCY_BOOST_MAX = 0.0003
CONFIRMED_BOOST = 0.0001
# 最後に話題に出てから半分の効き目になるまでの日数。好みや事情は数か月で変わりうるが、数週間では変わらないことが多い。
# Days until the recency boost halves. Preferences and circumstances can change over months but rarely within weeks.
RECENCY_HALF_LIFE_DAYS = 180.0

_SECONDS_PER_DAY = 86_400.0


def _is_kana(token: str) -> bool:
    return "\u3040" <= token <= "\u30ff"


def _is_word_match_evidence(token: str, *, word_has_pair: bool) -> bool:
    if len(token) != 1:
        return True
    if token.isascii():
        return token.isdigit()
    return not _is_kana(token) and not word_has_pair


def _query_terms(query: str) -> list[str]:
    """検索語のトークンのうち、語の一致の証拠にしてよいものを、重複なしで出現順に返す。空白で区切った語ごとに判定する。

    1 文字のトークンは、どの文にも現れるので原則として証拠にしない。英字 1 文字（"s" など）とかな 1 文字は常に除く。
    漢字 1 文字は、その語に 2 文字連続（bigram）が 1 つでもあれば除く（「犬の名前」の「前」が「以前」と一致しても関係はない）。
    「犬」のように 2 文字連続が作れない短い語のときだけ、漢字 1 文字も使う。数字は 1 文字でも使う。
    空白で区切るのは、tokenize_bm25 が空白をまたいで文字を連結し、別々のキーワード（「犬 猫」）から偽の 2 文字連続を作るため。

    The query's tokens that may count as word-match evidence, distinct and in order of first appearance, judged per
    whitespace-separated word.

    A single-character token appears in nearly any sentence, so it is not evidence by default. A single Latin letter ("s") and a
    single kana are always dropped. A single kanji is dropped when its word has any two-character pair (the 前 of 犬の名前 matching
    the 前 of 以前 means nothing); it is used only when the word is too short to make a pair, such as 犬. A digit counts even alone.
    Words are split on whitespace because tokenize_bm25 joins characters across whitespace and would make a false pair out of
    separate keywords such as "犬 猫".
    """
    terms: dict[str, None] = {}
    for word in str(query or "").split():
        tokens = list(dict.fromkeys(tokenize_bm25(word)))
        has_pair = any(len(token) == 2 and not token.isascii() for token in tokens)
        for token in tokens:
            if _is_word_match_evidence(token, word_has_pair=has_pair):
                terms.setdefault(token, None)
    return list(terms)


def _document_tokens(fact: Mapping[str, Any]) -> list[str]:
    return tokenize_bm25(f"{fact.get('title') or ''}\n{fact.get('content') or ''}")


def _bm25_scores(documents: Sequence[Sequence[str]], terms: Sequence[str]) -> list[float]:
    """全記憶を 1 つのコーパスとして、検索語の各トークンの BM25 を足し合わせる。語が 1 つも一致しない記憶は 0 になる。

    idf は常に正になる Lucene 方式（ln(1 + (N - n + 0.5) / (n + 0.5))）。Okapi 方式は半数以上の文書に現れる語で 0 以下になり、
    記憶が数件しかない利用者では一致した語が点を持たなくなるため使わない。

    BM25 over every memory as one corpus, summed over the query's tokens; a memory sharing no token scores 0.
    The idf is Lucene's always-positive form (ln(1 + (N - n + 0.5) / (n + 0.5))): the Okapi form is zero or
    negative for a term in half the documents or more, which would leave matched terms without a score for a
    user who has only a few memories.
    """
    total = len(documents)
    if not total or not terms:
        return [0.0] * total
    counts = [Counter(tokens) for tokens in documents]
    average_length = sum(len(tokens) for tokens in documents) / total or 1.0
    document_frequency = {term: sum(1 for count in counts if term in count) for term in terms}
    scores: list[float] = []
    for tokens, count in zip(documents, counts, strict=True):
        length_norm = 1 - BM25_B + BM25_B * len(tokens) / average_length
        score = 0.0
        for term in terms:
            frequency = count.get(term, 0)
            if not frequency:
                continue
            matching = document_frequency[term]
            idf = math.log(1 + (total - matching + 0.5) / (matching + 0.5))
            score += idf * frequency * (BM25_K1 + 1) / (frequency + BM25_K1 * length_norm)
        scores.append(score)
    return scores


def _ranks(ordered_ids: Sequence[int]) -> dict[int, int]:
    return {fact_id: rank for rank, fact_id in enumerate(ordered_ids, start=1)}


def _recency_boost(last_mentioned_at: Any, now: datetime) -> float:
    if not isinstance(last_mentioned_at, datetime):
        return 0.0
    moment = last_mentioned_at if last_mentioned_at.tzinfo is not None else last_mentioned_at.replace(tzinfo=UTC)
    age_days = max((now - moment).total_seconds(), 0.0) / _SECONDS_PER_DAY
    return RECENCY_BOOST_MAX * 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def _boost(fact: Mapping[str, Any], now: datetime) -> float:
    importance = max(0, min(int(fact.get("importance") if fact.get("importance") is not None else 50), 100))
    confirmed = CONFIRMED_BOOST if fact.get("last_confirmed_at") is not None else 0.0
    return IMPORTANCE_BOOST_MAX * importance / 100 + _recency_boost(fact.get("last_mentioned_at"), now) + confirmed


def rank_memory_facts(
    facts: Sequence[Mapping[str, Any]],
    query: str,
    *,
    now: datetime | None = None,
    limit: int = MEMORY_SEARCH_RESULT_LIMIT,
    max_distance: float | None = None,
) -> list[Mapping[str, Any]]:
    """検索語に関係のある記憶を、融合した順位の高い順に最大 `limit` 件返す。

    各行は id、title、content、importance、last_confirmed_at、last_mentioned_at と、検索語の埋め込みとのコサイン距離 distance を持つ。
    distance が None の行は、ベクトルがまだ無い記憶、または埋め込みが使えなかったときの行で、語の一致だけで順位づける。
    返す条件は、語の一致が 1 つ以上ある、または distance が max_distance（既定は意味検索のしきい値）以内であること。
    順位は、語の一致の一覧と意味の近さの一覧の RRF に小さな加点を足した点の降順で、同点は id の大きい順。

    Return at most `limit` memories relevant to the query, best fused rank first.

    Each row carries id, title, content, importance, last_confirmed_at, last_mentioned_at and `distance`, the
    cosine distance to the query embedding. A None distance means the memory has no vector yet or embeddings
    were unavailable, so it is ranked by word match alone. A memory is returned when it shares at least one
    word with the query or its distance is within max_distance (the semantic search threshold by default).
    Order is the RRF of the lexical and semantic lists plus the small boosts, descending, with ties broken by
    larger id.
    """
    if not facts or limit <= 0:
        return []
    moment = now if now is not None else datetime.now(UTC)
    ceiling = get_semantic_max_distance() if max_distance is None else max_distance
    terms = _query_terms(str(query or ""))

    lexical_scores = _bm25_scores([_document_tokens(fact) for fact in facts], terms)
    lexical_matches = [(fact, score) for fact, score in zip(facts, lexical_scores, strict=True) if score > 0]
    # 同点は id の大きい順にして、同じ入力なら必ず同じ順位になるようにする。
    # Ties go to the larger id so the same input always gives the same order.
    lexical_order = [int(fact["id"]) for fact, _ in sorted(lexical_matches, key=lambda item: (-item[1], -int(item[0]["id"])))]
    semantic_matches = [
        fact for fact in facts if fact.get("distance") is not None and float(fact["distance"]) <= ceiling
    ]
    semantic_order = [
        int(fact["id"]) for fact in sorted(semantic_matches, key=lambda fact: (float(fact["distance"]), -int(fact["id"])))
    ]

    lexical_rank = _ranks(lexical_order)
    semantic_rank = _ranks(semantic_order)
    scored: list[tuple[float, int, Mapping[str, Any]]] = []
    for fact in facts:
        fact_id = int(fact["id"])
        if fact_id not in lexical_rank and fact_id not in semantic_rank:
            continue
        fused = sum(1 / (RRF_K + ranks[fact_id]) for ranks in (lexical_rank, semantic_rank) if fact_id in ranks)
        scored.append((fused + _boost(fact, moment), fact_id, fact))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    return [fact for _, _, fact in scored[:limit]]
