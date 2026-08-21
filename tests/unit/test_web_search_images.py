import unittest
from unittest.mock import patch

from services import web_search
from services.web_search_images import (
    WebSearchImageCandidate,
    _is_non_photo_image_url,
    append_web_search_image_part,
    choose_web_search_image,
)


def _result() -> web_search.WebSearchResult:
    return web_search.WebSearchResult(
        query="京都の紅葉名所",
        searched_at="2026-08-19T00:00:00+00:00",
        sources=(
            web_search.WebSearchSource(
                url="https://example.com/kyoto",
                title="京都の紅葉ガイド",
                hostname="example.com",
                age="",
                snippets=(),
                image_candidates=(
                    WebSearchImageCandidate(
                        url="https://example.com/images/maple.jpg",
                        alt="嵐山の紅葉",
                        kind="og:image",
                    ),
                    WebSearchImageCandidate(
                        url="https://example.com/images/togetsukyo.jpg",
                        alt="渡月橋の紅葉",
                        kind="img",
                    ),
                    WebSearchImageCandidate(
                        url="https://example.com/images/logo.svg",
                        alt="Example logo",
                        kind="img",
                    ),
                    WebSearchImageCandidate(
                        url="https://example.com/assets/noimage.png",
                        alt="嵐山の紅葉",
                        kind="img",
                    ),
                ),
            ),
        ),
    )


class NonPhotoImageUrlTestCase(unittest.TestCase):
    def test_placeholders_and_site_furniture_are_rejected(self):
        for url in (
            "https://example.com/assets/noimage.png",
            "https://example.com/img/no_image.jpg",
            "https://example.com/img/no-photo.gif",
            "https://cdn.example.com/common/logo.svg",
            "https://cdn.example.com/ui/icons/search.png",
            "https://example.com/px/1x1.gif",
            "https://example.com/lazy-placeholder.png",
            "https://example.com/spacer.gif",
            "https://example.com/site-banner.jpg",
            "https://example.com/avatar/user12.jpg",
        ):
            with self.subTest(url=url):
                self.assertTrue(_is_non_photo_image_url(url))

    def test_real_photos_are_kept(self):
        # 語として一致させるので、iconic のような部分一致では落とさない。
        # Whole-word matching keeps photos whose name merely contains a marker.
        for url in (
            "https://example.com/images/maple.jpg",
            "https://example.com/photos/iconic-view.jpg",
            "https://example.com/wp-content/2026/08/kamakura-daibutsu.jpg",
            "https://example.com/media/hasedera_ajisai_2026.jpg",
            "https://example.com/photo/blanket-store.jpg",
            "https://img.example.com/resize?url=https://x.example/logo-hill.jpg",
        ):
            with self.subTest(url=url):
                self.assertFalse(_is_non_photo_image_url(url))


class WebSearchImageSelectionTestCase(unittest.TestCase):
    def test_llm_can_select_one_relevant_image(self):
        with patch(
            "services.web_search_images.get_llm_json_response",
            return_value=(
                '{"show_image": true, "image_id": "image-1", '
                '"alt_text": "嵐山の紅葉風景", "reason": "景観の説明に役立つ"}'
            ),
        ) as mock_llm:
            selection = choose_web_search_image("京都の紅葉名所を画像付きで教えて", _result())

        self.assertEqual(
            selection,
            {
                "url": "https://example.com/images/maple.jpg",
                "alt": "嵐山の紅葉風景",
                "source_url": "https://example.com/kyoto",
                "source_title": "京都の紅葉ガイド",
            },
        )
        prompt = mock_llm.call_args.args[0][1]["content"]
        self.assertIn("image-1", prompt)
        self.assertIn("image-2", prompt)
        system_prompt = mock_llm.call_args.args[0][0]["content"]
        self.assertIn("below the answer-trace panel and above the explanation", system_prompt)
        self.assertIn("mutually exclusive", system_prompt)
        self.assertIn("places and travel destinations", system_prompt)
        self.assertIn("programming, legal explanations", system_prompt)
        self.assertIn("Relevance is the highest priority", system_prompt)
        self.assertIn("sufficient quality", system_prompt)
        self.assertIn("non-duplication", system_prompt)
        self.assertIn("large watermarks", system_prompt)

    def test_placeholder_and_site_furniture_candidates_never_reach_the_llm(self):
        # 空の枠になる素材（noimage 等）とロゴは、選定LLMへ渡す前に落とす。
        # Assets that render as an empty frame and site logos are dropped before
        # the selection LLM ever sees them.
        with patch(
            "services.web_search_images.get_llm_json_response",
            return_value='{"show_image": false, "image_id": "", "alt_text": ""}',
        ) as mock_llm:
            choose_web_search_image("京都の紅葉名所を教えて", _result())

        prompt = mock_llm.call_args.args[0][1]["content"]
        self.assertIn("https://example.com/images/maple.jpg", prompt)
        self.assertIn("https://example.com/images/togetsukyo.jpg", prompt)
        self.assertNotIn("logo.svg", prompt)
        self.assertNotIn("noimage.png", prompt)

    def test_selection_prompt_rejects_broken_and_non_photo_candidates(self):
        with patch(
            "services.web_search_images.get_llm_json_response",
            return_value='{"show_image": false, "image_id": "", "alt_text": ""}',
        ) as mock_llm:
            choose_web_search_image("京都の紅葉名所を教えて", _result())

        system_prompt = mock_llm.call_args.args[0][0]["content"]
        self.assertIn("real photograph or a substantive diagram of the subject", system_prompt)
        self.assertIn("empty or broken frame", system_prompt)
        self.assertIn("gallery-listing page", system_prompt)
        self.assertIn("return show_image=false", system_prompt)

    def test_llm_can_decide_that_no_image_is_needed(self):
        with patch(
            "services.web_search_images.get_llm_json_response",
            return_value='{"show_image": false, "image_id": "", "alt_text": "", "reason": "text is enough"}',
        ):
            self.assertIsNone(choose_web_search_image("京都の紅葉の見頃を教えて", _result()))

    def test_unknown_candidate_id_is_never_rendered(self):
        with patch(
            "services.web_search_images.get_llm_json_response",
            return_value='{"show_image": true, "image_id": "image-99", "alt_text": "x"}',
        ):
            self.assertIsNone(choose_web_search_image("画像を見せて", _result()))

    def test_builds_a_structured_image_part(self):
        part = append_web_search_image_part(
            [{"type": "text", "text": "回答"}],
            {
                "url": "https://example.com/image.jpg",
                "alt": "説明",
                "source_url": "https://example.com/article",
                "source_title": "記事",
            },
        )

        self.assertEqual(part[0]["type"], "web_search_image")
        self.assertEqual(part[0]["image"]["source_url"], "https://example.com/article")
        self.assertEqual(part[1], {"type": "text", "text": "回答"})

    def test_does_not_add_image_when_a_generated_ui_is_present(self):
        parts = append_web_search_image_part(
            [
                {"type": "text", "text": "説明"},
                {"type": "sandbox_artifact", "artifact": {"title": "図"}},
            ],
            {
                "url": "https://example.com/image.jpg",
                "alt": "説明",
                "source_url": "https://example.com/article",
            },
        )

        self.assertEqual(
            parts,
            [
                {"type": "text", "text": "説明"},
                {"type": "sandbox_artifact", "artifact": {"title": "図"}},
            ],
        )

    def test_rejects_non_http_image_selection(self):
        part = append_web_search_image_part(
            None,
            {
                "url": "javascript:alert(1)",
                "alt": "危険",
                "source_url": "https://example.com/article",
            },
        )
        self.assertIsNone(part)


if __name__ == "__main__":
    unittest.main()
