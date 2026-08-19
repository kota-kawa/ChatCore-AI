import unittest
from unittest.mock import patch

from services import web_search
from services.web_search_images import (
    WebSearchImageCandidate,
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
                        url="https://example.com/images/logo.svg",
                        alt="Example logo",
                        kind="img",
                    ),
                ),
            ),
        ),
    )


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

        self.assertEqual(part[1]["type"], "web_search_image")
        self.assertEqual(part[1]["image"]["source_url"], "https://example.com/article")

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
