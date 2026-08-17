import unittest

from services.search_terms import (
    MAX_SEARCH_TERMS,
    build_like_pattern,
    escape_like_term,
    split_search_terms,
)


class SplitSearchTermsTestCase(unittest.TestCase):
    def test_splits_on_ascii_and_full_width_whitespace(self):
        self.assertEqual(
            split_search_terms("沖縄旅行　予算 メモ"),
            ["沖縄旅行", "予算", "メモ"],
        )

    def test_splits_on_punctuation(self):
        self.assertEqual(split_search_terms("deploy, checklist。本番"), ["deploy", "checklist", "本番"])

    def test_keeps_a_single_japanese_phrase_intact(self):
        # 形態素解析なしで助詞分割はしない（誤分割を避ける）。
        # No particle splitting without a morphological analyzer.
        self.assertEqual(split_search_terms("今月の目標"), ["今月の目標"])

    def test_deduplicates_and_caps_terms(self):
        terms = split_search_terms("a a b c d e f g h i j")

        self.assertEqual(terms[:3], ["a", "b", "c"])
        self.assertEqual(len(terms), MAX_SEARCH_TERMS)

    def test_blank_query_yields_no_terms(self):
        self.assertEqual(split_search_terms("   "), [])
        self.assertEqual(split_search_terms(""), [])


class LikeEscapingTestCase(unittest.TestCase):
    def test_wildcards_are_escaped(self):
        self.assertEqual(escape_like_term("100%_x"), "100\\%\\_x")

    def test_backslash_is_escaped_before_wildcards(self):
        self.assertEqual(escape_like_term("a\\%"), "a\\\\\\%")

    def test_pattern_wraps_the_escaped_term(self):
        self.assertEqual(build_like_pattern("50%"), "%50\\%%")


if __name__ == "__main__":
    unittest.main()
