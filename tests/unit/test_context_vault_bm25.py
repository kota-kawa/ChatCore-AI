"""文脈の事実の重複排除に使う BM25 の分かち書きと filter_bm25_duplicates（英語・日本語の近似重複の除去）
を検証するテスト。

Tests the BM25 tokenizer and filter_bm25_duplicates, which drop near-duplicate context facts in English and
Japanese.
"""

import unittest

from services.bm25 import tokenize_bm25
from services.context_vault_bm25 import filter_bm25_duplicates, find_bm25_duplicates


# 日本語: 重複判定に渡す事実 1 件分の辞書を作ります。
# English: Build one fact dict to feed the duplicate filter.
def _document(title, content, *, fact_type="project"):
    return {
        "fact_type": fact_type,
        "title": title,
        "content": content,
    }


# 日本語: 同じ種別の近似重複だけを除き、種別が違えば残すことを確認します。
# English: Check that only near-duplicates of the same fact type are dropped and different types are kept.
class ContextVaultBm25TestCase(unittest.TestCase):
    def test_tokenizes_ascii_words_and_normalized_cjk_ngrams(self):
        tokens = tokenize_bm25("ＦａｓｔＡＰＩで開発")

        self.assertIn("fastapi", tokens)
        self.assertIn("開発", tokens)
        self.assertIn("開", tokens)

    def test_filters_english_and_japanese_near_duplicates(self):
        existing = [
            _document(
                "Chat-Core backend framework",
                "The Chat-Core backend is built with FastAPI.",
            ),
            _document(
                "ビッグテックへのキャリア転換",
                "ビッグテック企業への転職を検討している",
            ),
        ]
        candidates = [
            _document(
                "Chat-Core backend",
                "Chat-Core uses FastAPI for its backend.",
            ),
            _document(
                "Big Tech転職",
                "Big Tech企業への転職を長期的に検討している",
            ),
            _document(
                "Rust compiler",
                "Uses Rust for an ongoing compiler project.",
            ),
        ]

        self.assertEqual(
            filter_bm25_duplicates(candidates, existing),
            [candidates[2]],
        )

    def test_keeps_similar_words_when_fact_types_differ(self):
        existing = [
            _document(
                "Rust project",
                "Uses Rust for an ongoing compiler project.",
                fact_type="project",
            )
        ]
        candidate = _document(
            "Rust preference",
            "Prefers future code examples in Rust.",
            fact_type="preference",
        )

        self.assertEqual(filter_bm25_duplicates([candidate], existing), [candidate])

    def test_filters_near_duplicates_within_the_same_batch(self):
        candidates = [
            _document(
                "Chat-Core backend framework",
                "The Chat-Core backend is built with FastAPI.",
            ),
            _document(
                "Chat-Core backend",
                "Chat-Core uses FastAPI for its backend.",
            ),
        ]

        self.assertEqual(filter_bm25_duplicates(candidates, []), [candidates[0]])

    def test_find_returns_the_matched_document_for_each_candidate(self):
        existing = [
            {**_document("Chat-Core backend framework", "The Chat-Core backend is built with FastAPI."), "fact_id": 12},
            {**_document("Rust compiler", "Uses Rust for an ongoing compiler project."), "fact_id": 13},
        ]
        candidates = [
            _document("Chat-Core backend", "Chat-Core uses FastAPI for its backend."),
            _document("Deep sea fish research", "Researches deep sea fish as an occupation."),
            _document("Chat-Core server", "The Chat-Core server uses FastAPI."),
        ]

        matches = find_bm25_duplicates(candidates, existing)

        # 既存文書の一致はその文書(fact_id つき)、重複なしは None、同一バッチの一致は先に残った候補そのもの。
        # An existing match is that document (with its fact_id), a unique candidate is None, and a same-batch
        # match is the earlier candidate itself.
        self.assertEqual(matches[0]["fact_id"], 12)
        self.assertIsNone(matches[1])
        self.assertEqual(matches[2]["fact_id"], 12)
        self.assertEqual(
            filter_bm25_duplicates(candidates, existing),
            [candidates[1]],
        )

    def test_find_matches_an_earlier_candidate_of_the_same_batch(self):
        candidates = [
            _document("Chat-Core backend framework", "The Chat-Core backend is built with FastAPI."),
            _document("Chat-Core backend", "Chat-Core uses FastAPI for its backend."),
        ]

        matches = find_bm25_duplicates(candidates, [])

        self.assertIsNone(matches[0])
        self.assertIs(matches[1], candidates[0])


if __name__ == "__main__":
    unittest.main()
