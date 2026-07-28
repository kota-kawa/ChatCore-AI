import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import manual_rag


class ManualRagLocalesTestCase(unittest.TestCase):
    def tearDown(self):
        manual_rag._indexes.clear()

    def test_english_manual_corpus_is_loaded_separately(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            index = manual_rag.ManualRagIndex(
                manual_rag.MANUAL_DIRS["en"],
                locale="en",
            )

        self.assertEqual(index.locale, "en")
        self.assertTrue(index._chunks)
        combined = "\n".join(chunk.content for chunk in index._chunks)
        self.assertIn("Change the interface language in Settings", combined)

    def test_locale_indexes_use_distinct_cache_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            japanese_dir = root / "ja"
            english_dir = root / "en"
            japanese_dir.mkdir()
            english_dir.mkdir()
            (japanese_dir / "guide.md").write_text("# Guide\n\n## Topic\n\n日本語", encoding="utf-8")
            (english_dir / "guide.md").write_text("# Guide\n\n## Topic\n\nEnglish", encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                japanese = manual_rag.ManualRagIndex(japanese_dir, locale="ja")
                english = manual_rag.ManualRagIndex(english_dir, locale="en")

        self.assertNotEqual(japanese._cache_file, english._cache_file)
        self.assertEqual(japanese._chunks[0].content, "日本語")
        self.assertEqual(english._chunks[0].content, "English")

    def test_search_manual_selects_requested_locale(self):
        class FakeIndex:
            def search(self, query, top_k):
                return [manual_rag.ManualChunk("Language", "English settings", "Settings")]

        with patch("services.manual_rag.get_manual_rag_index", return_value=FakeIndex()) as get_index:
            result = manual_rag.search_manual("language", locale="en")

        get_index.assert_called_once_with("en")
        self.assertIn("Operation manual (reference)", result)
        self.assertIn("English settings", result)


if __name__ == "__main__":
    unittest.main()
