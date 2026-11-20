"""記憶の検索の順位づけ（語の一致と意味の近さの融合、小さな加点、下限）を、固定の小さなデータで決定的に検証するテスト（ADR 0025）。

Tests memory-search ranking (the fusion of word match and semantic closeness, the small boosts and the floor)
on a small fixed data set, deterministically.
"""

import random
import unittest
from datetime import UTC, datetime, timedelta

from services.memory_search_ranking import (
    CONFIRMED_BOOST,
    IMPORTANCE_BOOST_MAX,
    MEMORY_SEARCH_RESULT_LIMIT,
    RECENCY_BOOST_MAX,
    WORD_MATCH_MIN_COVERAGE,
    rank_memory_facts,
)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

# (id, 種類, タイトル, 内容, 重要度)。10 件の固定データ。
# (id, type, title, content, importance): ten fixed memories.
_FACTS = [
    (1, "profile", "居住地", "東京の渋谷区に住んでいる。", 70),
    (2, "preference", "好きな食べ物", "ラーメンが好き。特に味噌ラーメン。", 50),
    (3, "project", "Chat Core の開発", "Python と FastAPI でチャットアプリを開発している。", 80),
    (4, "preference", "飼い犬", "柴犬のハチを飼っている。散歩は朝。", 60),
    (5, "profile", "勤務先", "株式会社サンプルでエンジニアとして働いている。", 70),
    (6, "decision", "運動の習慣", "毎週末にジョギングをする。", 30),
    (7, "reference", "English study", "Studying English with a daily podcast.", 40),
    (8, "preference", "コーヒー", "ブラックコーヒーを一日二杯飲む。", 20),
    (9, "project", "旅行計画", "来年の春に京都へ旅行する予定。", 50),
    (10, "profile", "アレルギー", "そばアレルギーがある。", 90),
]


def _rows(distances=None, **overrides):
    distances = distances or {}
    return [
        {
            "id": fact_id,
            "fact_type": fact_type,
            "title": title,
            "content": content,
            "importance": importance,
            "source_kind": "chat",
            "last_confirmed_at": None,
            "last_mentioned_at": NOW - timedelta(days=400),
            "distance": distances.get(fact_id),
            **overrides,
        }
        for fact_id, fact_type, title, content, importance in _FACTS
    ]


def _ids(rows, query, **kwargs):
    return [fact["id"] for fact in rank_memory_facts(rows, query, now=NOW, **kwargs)]


class FusionTestCase(unittest.TestCase):
    def test_a_word_match_alone_finds_the_memory(self):
        self.assertEqual(_ids(_rows(), "犬の散歩"), [4])
        self.assertEqual(_ids(_rows(), "english podcast"), [7])
        self.assertEqual(_ids(_rows(), "アレルギー"), [10])

    def test_semantic_closeness_alone_finds_a_memory_with_no_shared_word(self):
        # 「pet」はどの記憶にも現れないが、犬の記憶は意味が近い。
        # "pet" appears in no memory, yet the dog memory is semantically close.
        self.assertEqual(_ids(_rows({4: 0.3, 2: 0.9}), "pet"), [4])

    def test_a_memory_found_by_both_ranks_above_one_found_by_meaning_only(self):
        # 2 は語（ラーメン）も意味も合い、8 は意味だけが近い。
        # 2 matches the word and the meaning; 8 is only close in meaning.
        self.assertEqual(_ids(_rows({2: 0.4, 8: 0.2}), "ラーメン"), [2, 8])

    def test_a_memory_found_by_meaning_ranks_below_a_better_word_match_even_if_closer(self):
        # 語の一致 1 位 + 意味 2 位 の記憶が、意味だけ 1 位の記憶より上に来る。
        # Word-match rank 1 plus semantic rank 2 beats semantic rank 1 alone.
        rows = _rows({2: 0.3, 8: 0.1})
        self.assertEqual(_ids(rows, "ラーメン"), [2, 8])

    def test_memories_found_by_meaning_alone_are_ordered_by_distance(self):
        # 語の一致が無いので、順位は意味の近さだけで決まる（id の大きい順ではない）。
        # With no word match, the order comes from semantic closeness alone (not from the larger id).
        self.assertEqual(_ids(_rows({4: 0.3, 8: 0.5}), "pet"), [4, 8])
        self.assertEqual(_ids(_rows({4: 0.5, 8: 0.3}), "pet"), [8, 4])

    def test_the_result_is_capped_at_the_limit(self):
        rows = [
            {**_rows()[0], "id": number, "title": "alpha", "content": f"alpha {'x' * number}"} for number in range(1, 13)
        ]

        self.assertEqual(len(_ids(rows, "alpha")), MEMORY_SEARCH_RESULT_LIMIT)
        self.assertEqual(MEMORY_SEARCH_RESULT_LIMIT, 5)
        self.assertEqual(len(_ids(rows, "alpha", limit=2)), 2)


class FloorTestCase(unittest.TestCase):
    def test_a_far_memory_with_no_shared_word_is_dropped(self):
        far = {fact_id: 0.9 for fact_id, *_ in _FACTS}

        self.assertEqual(_ids(_rows(far), "pet"), [])

    def test_the_distance_threshold_is_inclusive(self):
        self.assertEqual(_ids(_rows({4: 0.75}), "pet"), [4])
        self.assertEqual(_ids(_rows({4: 0.7501}), "pet"), [])
        self.assertEqual(_ids(_rows({4: 0.9}), "pet", max_distance=0.95), [4])

    def test_a_far_memory_that_shares_a_word_is_still_returned(self):
        self.assertEqual(_ids(_rows({4: 0.95}), "犬の散歩"), [4])

    def test_particles_and_single_latin_letters_are_not_a_word_match(self):
        # 「の」「は」だけの検索語は、どの記憶にも現れるが語の一致ではない。
        # A query of only "の" or "s" appears in nearly any memory but is no word match.
        self.assertEqual(_ids(_rows(), "の"), [])
        self.assertEqual(_ids(_rows(), "の は が"), [])
        self.assertEqual(_ids(_rows(), "s"), [])

    def test_one_shared_character_is_not_a_word_match_when_the_query_has_a_pair(self):
        # 「犬の名前」の「前」は「以前」の「前」と一致するが、関係はない。2 文字連続（犬の・名前）が合う記憶だけが語の一致になる。
        # The 前 of 犬の名前 matches the 前 of 以前, which means nothing: only a memory sharing a pair (犬の, 名前) is a word match.
        rows = _rows()
        rows[4]["content"] = "以前は株式会社サンプルに勤務。"

        self.assertEqual(_ids(rows, "犬の名前"), [4])
        self.assertNotIn(5, _ids(rows, "犬の名前"))
        self.assertEqual(_ids(_rows(), "食べ物は何"), [2])

    def test_a_query_too_short_to_make_a_pair_still_matches_by_its_single_kanji(self):
        self.assertEqual(_ids(_rows(), "犬"), [4])
        self.assertEqual(_ids(_rows(), "犬 猫"), [4])

    def test_a_digit_counts_as_a_word_even_alone(self):
        rows = [{**_rows()[0], "id": 51, "title": "年数", "content": "勤続 5 年"}, {**_rows()[0], "id": 52, "content": "別の話"}]

        self.assertEqual(_ids(rows, "5"), [51])

    def test_an_empty_query_or_no_memory_gives_nothing(self):
        self.assertEqual(_ids(_rows(), ""), [])
        self.assertEqual(_ids([], "犬"), [])


def _custom_rows(*memories, distances=None):
    """(id, タイトル, 内容) の組から、固定データとは別の記憶の行を作る。Build rows from (id, title, content) apart from the fixed set."""
    distances = distances or {}
    return [
        {
            "id": fact_id,
            "fact_type": "preference",
            "title": title,
            "content": content,
            "importance": 50,
            "source_kind": "chat",
            "last_confirmed_at": None,
            "last_mentioned_at": NOW - timedelta(days=400),
            "distance": distances.get(fact_id),
        }
        for fact_id, title, content in memories
    ]


class WordMatchCoverageTestCase(unittest.TestCase):
    """語の一致は、検索語のどれか 1 語の証拠のトークンの一定割合が記憶に現れたときだけ数える。

    A word match counts only when a memory holds a minimum share of the evidence tokens of some one query word.
    """

    COMMIT = (1, "コミットメッセージ", "コミットメッセージは日本語と英語を併記する。")
    REPORT = (2, "週報のフォーマット", "週報は箇条書きで、毎週金曜に出す。")

    def test_the_threshold_is_the_documented_starting_point(self):
        self.assertEqual(WORD_MATCH_MIN_COVERAGE, 0.3)

    def test_a_single_shared_bigram_is_not_a_word_match(self):
        # 「フォーマット」と「コミットメッセージ」が共有するのは「ット」だけ（「フォーマット」の証拠のトークン 4 個のうち 1 個 = 25%。長音は索引で落ちる）。
        # フォーマット and コミットメッセージ share only "ット" (1 of 5 evidence tokens).
        rows = _custom_rows(self.COMMIT, self.REPORT)

        self.assertEqual(_ids(rows, "週報 フォーマット"), [2])
        self.assertEqual(_ids(rows, "週報のフォーマット"), [2])

    def test_a_memory_dropped_from_the_word_list_still_enters_by_meaning(self):
        rows = _custom_rows(self.COMMIT, self.REPORT, distances={1: 0.4})

        self.assertEqual(set(_ids(rows, "週報 フォーマット")), {1, 2})

    def test_a_dropped_memory_does_not_defeat_the_untrusted_stop_of_auto_run(self):
        # 語の一致から外れた記憶は結果に入らないので、本人由来でない記憶でも自動実行を止める理由にならない。
        # A memory dropped from the word list is not in the result, so even a non-owner memory gives no reason to stop auto-run.
        rows = _custom_rows(self.COMMIT)
        rows[0]["source_kind"] = "mcp"

        self.assertEqual(_ids(rows, "週報 フォーマット"), [])

    def test_a_short_query_passes_on_one_match(self):
        # 証拠のトークンが 1〜3 個なら 1 個の一致で通る。
        # With 1-3 evidence tokens one match is enough.
        rows = _custom_rows((1, "旅行計画", "来年の春に京都へ旅行する予定。"), (2, "飼い犬", "柴犬のハチを飼っている。"))

        self.assertEqual(_ids(rows, "京都"), [1])
        self.assertEqual(_ids(rows, "旅行 ハチ"), [1, 2])
        self.assertEqual(_ids(rows, "project plan budget"), [])
        english = _custom_rows((3, "Project", "The project is due Friday."))
        self.assertEqual(_ids(english, "project plan budget"), [3])

    def test_a_keyword_list_keeps_a_memory_matching_only_one_of_its_words(self):
        # 割合は語ごとに見る。キーワードを足しても、1 語だけが当たる関連する記憶は語の一致に残る。
        # The share is taken per word, so adding keywords does not drop a related memory that matches only one of them.
        rows = _custom_rows((1, "Project", "The project plan is due Friday."), (2, "Budget", "The budget is fixed."))

        self.assertEqual(_ids(rows, "project plan budget deadline owner"), [1, 2])
        self.assertEqual(_ids(rows, "project plan budget"), [1, 2])

    def test_a_keyword_list_from_the_model_finds_the_memory_and_skips_a_partial_word(self):
        # モデルが実際に送った形の検索語（5 語）。「犬」だけが当たる飼い犬の記憶は入り、「プレゼント」と「ント」だけを
        # 共有する無関係な記憶（4 個中 1 個 = 25%）は入らない。
        # A five-keyword query as a model actually sent it: the dog memory matching only 犬 is found, and an unrelated memory
        # sharing just ント with プレゼント (1 of 4 = 25%) is not.
        dog = (1, "飼い犬", "柴犬のハチ（オス、3歳）を飼っている。散歩は朝。")
        partial = (2, "レビュー", "コメントは短く書く。")
        rows = _custom_rows(dog, partial)

        self.assertEqual(_ids(rows, "犬 犬種 年齢 誕生日 プレゼント"), [1])

    def test_a_partial_match_between_short_words_still_enters_the_word_list(self):
        # 既知の限界: 証拠のトークンが 1〜3 個の短い語は 1 個の一致で通るので、「ラーメン」（ラメ・メン）と「メンバー」の
        # 「メン」のような、短い語どうしの語の一部の一致は外せない。
        # Known limit: a short word of 1-3 evidence tokens passes on one match, so a partial match between short words
        # (the メン shared by ラーメン and メンバー) cannot be dropped.
        rows = _custom_rows((1, "好きな食べ物", "ラーメンが好き。"), (2, "チーム", "メンバーは5人。"))

        self.assertEqual(_ids(rows, "ラーメン 好み 店"), [1, 2])

    def test_a_sentence_query_with_one_content_word_misses_by_word_and_is_found_by_meaning(self):
        # 既知の限界: 空白の無い文の形の検索語は 1 語として扱う。内容のある語が 1 つだけ一致する記憶（10 個中 2 個 = 20%）は
        # 語の一致からは外れ、意味の近さがしきい値以内のときだけ入る。
        # Known limit: a sentence-shaped query without spaces is one word. A memory matching only one content word (2 of 10 = 20%)
        # is not a word match; it is found only when its meaning is within the threshold.
        food = (1, "好きな食べ物", "ラーメンが好き。")

        self.assertEqual(_ids(_custom_rows(food), "今日の食べ物は何がいい"), [])
        self.assertEqual(_ids(_custom_rows(food, distances={1: 0.3}), "今日の食べ物は何がいい"), [1])

    def test_a_sentence_query_needs_a_coherent_run_not_one_bigram(self):
        # 「犬の名前を教えて」の証拠のトークンは 7 個。「犬の」「の名」「名前」が揃う記憶は通り、「犬の」だけの記憶は外れる。
        # 犬の名前を教えて has 7 evidence tokens: a memory with 犬の / の名 / 名前 passes, one with only 犬の drops out.
        coherent = (1, "犬の名前", "飼い犬の名前はハチ。")
        only_one = (2, "犬のおやつ", "犬のおやつはささみ。")
        rows = _custom_rows(coherent, only_one)

        self.assertEqual(_ids(rows, "犬の名前を教えて"), [1])

    def test_a_single_kanji_query_is_unaffected(self):
        rows = _custom_rows((1, "飼い犬", "柴犬のハチ。"), (2, "コーヒー", "ブラックを飲む。"))

        self.assertEqual(_ids(rows, "犬"), [1])

    def test_an_english_query_whose_function_words_match_still_enters_the_word_list(self):
        # 既知の限界: 英語の機能語（is・the など）の一致も語の一致として数える。機能語の一覧は持たない（BM25 の idf が低く出るだけ）。
        # Known limit: English function words (is, the) still count; no stop-word list is kept, only the low idf lowers them.
        rows = _custom_rows((1, "Coffee", "This is the best coffee in town."))

        self.assertEqual(_ids(rows, "what is the project plan"), [1])
        # 語ごとに見るので、長い英文でも "the" 1 語の一致で入る。
        # Taken per word, a long English sentence still matches on "the" alone.
        self.assertEqual(_ids(rows, "tell me about the weather in the mountains"), [1])


class MissingVectorTestCase(unittest.TestCase):
    def test_memories_without_a_vector_are_ranked_by_word_match_alone(self):
        # 検索語の埋め込みが無い（利用不可・失敗）とき、全行の distance は None。語の一致だけで順位が付き、検索は落ちない。
        # With no query embedding (unavailable or failed) every distance is None; ranking uses word match and the search does not fail.
        self.assertEqual(_ids(_rows(), "ラーメン"), [2])

    def test_a_memory_with_no_vector_still_matches_by_word_while_others_match_by_meaning(self):
        # 4 はベクトルが無いが語が合う。8 はベクトルがあり意味が近い。どちらも返る。
        # 4 has no vector but matches the word; 8 has one and is close in meaning. Both are returned.
        rows = _rows({8: 0.2})

        self.assertEqual(set(_ids(rows, "犬の散歩")), {4, 8})
        self.assertNotIn(6, _ids(rows, "犬の散歩"))

    def test_a_memory_with_no_vector_and_no_shared_word_is_not_returned(self):
        self.assertNotIn(6, _ids(_rows({4: 0.3}), "犬の散歩"))


class BoostTestCase(unittest.TestCase):
    def _rank_chain(self):
        # alpha を 1 回だけ含み、あとは詰め物の語で長くしただけの 20 件。短いほど BM25 が高く、語の一致の順位は id の昇順になる。
        # Twenty memories with one "alpha" each, lengthened only by filler words: shorter scores higher, so lexical order is ascending id.
        return [
            {
                **_rows()[0],
                "id": number,
                "title": "alpha",
                "content": "alpha " + "filler " * number,
                "importance": 0,
                "last_mentioned_at": NOW - timedelta(days=3650),
            }
            for number in range(1, 21)
        ]

    def test_without_boosts_the_order_follows_the_word_match(self):
        self.assertEqual(_ids(self._rank_chain(), "alpha", limit=20), list(range(1, 21)))

    def test_the_maximum_boost_moves_a_memory_only_a_few_places(self):
        rows = self._rank_chain()
        rows[19].update(importance=100, last_confirmed_at=NOW, last_mentioned_at=NOW)

        ranked = _ids(rows, "alpha", limit=20)

        self.assertEqual(ranked[0], 1)
        # 20 位の記憶が、満点の加点でも上位 10 位には届かない。
        # The 20th memory, with every boost at its maximum, still does not reach the top 10.
        self.assertGreater(ranked.index(20), 10)
        self.assertLess(ranked.index(20), 19)

    def test_the_boosts_together_stay_within_the_documented_ceiling(self):
        self.assertAlmostEqual(IMPORTANCE_BOOST_MAX + RECENCY_BOOST_MAX + CONFIRMED_BOOST, 0.0008)

    def test_a_boost_breaks_a_near_tie_in_favor_of_the_important_recent_confirmed_memory(self):
        rows = self._rank_chain()[:2]
        # 1 位と 2 位は語の一致の差がごくわずか。2 位に満点の加点があれば入れ替わる。
        # Ranks 1 and 2 differ only slightly in word match; the full boost swaps them.
        rows[1].update(importance=100, last_confirmed_at=NOW, last_mentioned_at=NOW)

        self.assertEqual(_ids(rows, "alpha"), [2, 1])

    def test_a_boost_never_lifts_a_word_only_match_above_a_match_by_word_and_meaning(self):
        rows = self._rank_chain()
        # 1 番目の記憶は語と意味の両方で当たり、20 番目は語の一致が最下位だが満点の加点を持つ。
        # Memory 1 matches by word and meaning; memory 20 is last by word match but has every boost.
        rows[0]["distance"] = 0.5
        rows[19].update(importance=100, last_confirmed_at=NOW, last_mentioned_at=NOW)

        self.assertEqual(_ids(rows, "alpha")[0], 1)

    def test_a_recent_mention_counts_more_than_an_old_one_and_a_future_date_is_not_extra(self):
        old = {**_rows()[3], "id": 31, "last_mentioned_at": NOW - timedelta(days=1000)}
        recent = {**_rows()[3], "id": 30, "last_mentioned_at": NOW - timedelta(days=1)}
        future = {**_rows()[3], "id": 29, "last_mentioned_at": NOW + timedelta(days=500)}

        # id の大きい順の同点処理に勝つため、id の小さい側に新しさの加点がある。
        # The recent memory has the smaller id, so only the recency boost can put it ahead.
        self.assertEqual(_ids([old, recent], "犬の散歩"), [30, 31])
        self.assertEqual(_ids([old, future], "犬の散歩"), [29, 31])

    def test_a_missing_mention_date_gets_no_recency_boost_and_a_naive_date_counts_as_utc(self):
        base = _rows()[3]
        none = {**base, "id": 41, "last_mentioned_at": None}
        naive = {**base, "id": 40, "last_mentioned_at": NOW.replace(tzinfo=None) - timedelta(days=1)}

        self.assertEqual(_ids([none, naive], "犬の散歩"), [40, 41])


class DeterminismTestCase(unittest.TestCase):
    def test_equal_scores_are_broken_by_the_larger_id(self):
        base = _rows()[3]
        twins = [{**base, "id": 3}, {**base, "id": 8}, {**base, "id": 5}]

        self.assertEqual(_ids(twins, "犬の散歩"), [8, 5, 3])

    def test_an_exact_tie_across_the_two_lists_is_broken_by_the_larger_id(self):
        # 3 は語の一致が 1 位・意味が 2 位、8 は語の一致が 2 位・意味が 1 位。融合した点は完全に同じで、加点も同じ。
        # 3 is first by word and second by meaning; 8 is second by word and first by meaning. Fused scores and boosts are exactly equal.
        base = _rows()[3]
        rows = [
            {**base, "id": 3, "title": "犬", "content": "犬の散歩", "distance": 0.5},
            {**base, "id": 8, "title": "犬", "content": "犬の散歩 と 長い補足の文章がここに続く", "distance": 0.2},
        ]

        self.assertEqual(_ids(rows, "犬の散歩"), [8, 3])
        self.assertEqual(_ids(list(reversed(rows)), "犬の散歩"), [8, 3])

    def test_the_same_rows_in_any_order_give_the_same_ranking(self):
        distances = {2: 0.2, 4: 0.5, 8: 0.6}
        reference = _ids(_rows(distances), "犬 ラーメン コーヒー")
        shuffled = _rows(distances)
        random.Random(7).shuffle(shuffled)

        self.assertEqual(_ids(shuffled, "犬 ラーメン コーヒー"), reference)
        self.assertEqual(_ids(_rows(distances), "犬 ラーメン コーヒー"), reference)


if __name__ == "__main__":
    unittest.main()
