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

# 語の一致を「証拠」として数えるのに必要な、検索語の 1 語（空白で区切った語）の証拠のトークンが記憶に現れた割合。どれか 1 語が
# この割合を満たせば、その記憶は語の一致の一覧に入る。日本語は 2 文字連続（bigram）で索引するので、無関係な記憶でも語の一部が
# たまたま一致する（「フォーマット」と「コミットメッセージ」が「ット」を共有する、など。5 個中 1 個 = 20%）。30% なら、そうした
# 語の一部だけの一致は外れ、証拠のトークンが 1〜3 個の短い語は 1 個の一致で通り、空白の無い文の形の検索語（「犬の名前を教えて」
# = 7 個）は 3 個（「犬の」「の名」「名前」のようなまとまった一致）が要る。割合を検索語の全体ではなく語ごとに見るのは、モデルが
# キーワードを並べた検索語（「犬 犬種 年齢 誕生日 プレゼント」）で、1 語だけが当たる関連する記憶を落とさないため（全体で見ると、
# 語を足すほど 1 語の一致の割合が下がる）。外れた記憶も、意味の近さがしきい値以内なら意味の一覧から入る。
# The share of one query word's evidence tokens (words are split on whitespace) a memory must contain for its word match to count.
# A memory enters the word list when any one word reaches this share. Japanese is indexed as character bigrams, so an unrelated
# memory shares part of a word by chance (the "ット" shared by フォーマット and コミットメッセージ: 1 of 5 = 20%). At 30% such
# partial matches drop out, a short word of 1-3 evidence tokens passes on one match, and a sentence-shaped query without spaces
# (犬の名前を教えて = 7 tokens) needs 3 (a coherent run such as 犬の / の名 / 名前). The share is taken per word, not over the
# whole query, so that a keyword-list query from the model (犬 犬種 年齢 誕生日 プレゼント) keeps a related memory matching
# only one of its words: over the whole query, every added keyword would lower the share of a single matching word.
# A dropped memory can still enter through the semantic list when its distance is within the threshold.
WORD_MATCH_MIN_COVERAGE = 0.3

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
    return list(dict.fromkeys(token for word in _query_words(query) for token in word))


def _query_words(query: str) -> list[list[str]]:
    """検索語を空白で区切った語ごとに、証拠にしてよいトークンを重複なしで返す（証拠のトークンが無い語は除く）。

    The evidence tokens of each whitespace-separated query word, distinct within the word; words with none are dropped.
    """
    words: list[list[str]] = []
    for word in str(query or "").split():
        tokens = list(dict.fromkeys(tokenize_bm25(word)))
        has_pair = any(len(token) == 2 and not token.isascii() for token in tokens)
        evidence = [token for token in tokens if _is_word_match_evidence(token, word_has_pair=has_pair)]
        if evidence:
            words.append(evidence)
    return words


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


def _covers_a_query_word(document: Sequence[str], words: Sequence[Sequence[str]]) -> bool:
    """記憶が、検索語のどれか 1 語について、その語の証拠のトークンを WORD_MATCH_MIN_COVERAGE 以上の割合で含むか。

    Whether the memory contains at least WORD_MATCH_MIN_COVERAGE of the evidence tokens of any one query word.
    """
    present = set(document)
    return any(sum(1 for token in word if token in present) / len(word) >= WORD_MATCH_MIN_COVERAGE for word in words)


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
    返す条件は、語の一致がある（検索語のどれか 1 語の証拠のトークンの WORD_MATCH_MIN_COVERAGE 以上が記憶に現れる）、または distance が
    max_distance（既定は意味検索のしきい値）以内であること。
    順位は、語の一致の一覧と意味の近さの一覧の RRF に小さな加点を足した点の降順で、同点は id の大きい順。

    Return at most `limit` memories relevant to the query, best fused rank first.

    Each row carries id, title, content, importance, last_confirmed_at, last_mentioned_at and `distance`, the
    cosine distance to the query embedding. A None distance means the memory has no vector yet or embeddings
    were unavailable, so it is ranked by word match alone. A memory is returned when it has a word match (at least
    WORD_MATCH_MIN_COVERAGE of the query's evidence tokens appear in it) or its distance is within max_distance (the
    semantic search threshold by default).
    Order is the RRF of the lexical and semantic lists plus the small boosts, descending, with ties broken by
    larger id.
    """
    if not facts or limit <= 0:
        return []
    moment = now if now is not None else datetime.now(UTC)
    ceiling = get_semantic_max_distance() if max_distance is None else max_distance
    words = _query_words(str(query or ""))
    terms = list(dict.fromkeys(token for word in words for token in word))

    documents = [_document_tokens(fact) for fact in facts]
    lexical_scores = _bm25_scores(documents, terms)
    lexical_matches = [
        (fact, score)
        for fact, score, document in zip(facts, lexical_scores, documents, strict=True)
        if score > 0 and _covers_a_query_word(document, words)
    ]
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
