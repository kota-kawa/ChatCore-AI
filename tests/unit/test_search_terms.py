import unittest

from services.search_terms import (
    MAX_SEARCH_TERMS,
    build_like_pattern,
    escape_like_term,
    kana_variants,
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


class KanaVariantsTestCase(unittest.TestCase):
    def test_hiragana_term_gains_its_katakana_spelling(self):
        self.assertEqual(kana_variants("ぱすぽーと"), ["ぱすぽーと", "パスポート"])

    def test_katakana_term_gains_its_hiragana_spelling(self):
        self.assertEqual(kana_variants("パスポート"), ["パスポート", "ぱすぽーと"])

    def test_mixed_term_gains_both_uniform_spellings(self):
        self.assertEqual(kana_variants("パスぽーと"), ["パスぽーと", "ぱすぽーと", "パスポート"])

    def test_terms_without_kana_have_no_variants(self):
        self.assertEqual(kana_variants("沖縄旅行"), ["沖縄旅行"])
        self.assertEqual(kana_variants("deploy"), ["deploy"])

    def test_kanji_okurigana_and_voiced_marks_are_converted(self):
        self.assertEqual(kana_variants("申し込みゔぁ"), ["申し込みゔぁ", "申シ込ミヴァ"])
        self.assertEqual(kana_variants("いすゞ"), ["いすゞ", "イスヾ"])

    def test_kana_without_a_counterpart_is_left_unchanged(self):
        self.assertEqual(kana_variants("ヷ"), ["ヷ"])

    def test_half_width_katakana_is_out_of_scope(self):
        self.assertEqual(kana_variants("ﾊﾟｽﾎﾟｰﾄ"), ["ﾊﾟｽﾎﾟｰﾄ"])


class LikeEscapingTestCase(unittest.TestCase):
    def test_wildcards_are_escaped(self):
        self.assertEqual(escape_like_term("100%_x"), "100\\%\\_x")

    def test_backslash_is_escaped_before_wildcards(self):
        self.assertEqual(escape_like_term("a\\%"), "a\\\\\\%")

    def test_pattern_wraps_the_escaped_term(self):
        self.assertEqual(build_like_pattern("50%"), "%50\\%%")


if __name__ == "__main__":
    unittest.main()
