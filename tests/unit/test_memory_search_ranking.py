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

    def test_an_empty_query_or_no_memory_gives_nothing(self):
        self.assertEqual(_ids(_rows(), ""), [])
        self.assertEqual(_ids([], "犬"), [])


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

    def test_the_same_rows_in_any_order_give_the_same_ranking(self):
        distances = {2: 0.2, 4: 0.5, 8: 0.6}
        reference = _ids(_rows(distances), "犬 ラーメン コーヒー")
        shuffled = _rows(distances)
        random.Random(7).shuffle(shuffled)

        self.assertEqual(_ids(shuffled, "犬 ラーメン コーヒー"), reference)
        self.assertEqual(_ids(_rows(distances), "犬 ラーメン コーヒー"), reference)


if __name__ == "__main__":
    unittest.main()
