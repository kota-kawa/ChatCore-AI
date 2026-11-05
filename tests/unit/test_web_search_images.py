"""Web 検索結果の画像選択 (services.web_search_images) のテスト。
非写真 URL の除外、LLM による画像選択と配置計画、回答パーツへの挿入を確かめる。

Tests for web-search image selection (services.web_search_images): non-photo URL filtering,
LLM image selection and placement plans, and insertion into answer parts.
"""

import unittest
from unittest.mock import patch

from services import web_search
from services.llm import LIGHTWEIGHT_TASK_MODEL, LIGHTWEIGHT_TASK_REASONING_EFFORT
from services.web_search_images import (
    IMAGE_SELECTION_REASONING_FORMAT,
    WebSearchImageCandidate,
    _is_non_photo_image_url,
    append_web_search_image_parts,
    build_web_search_image_parts,
    choose_web_search_images,
    find_next_streaming_image_insertion,
)


# 日本語: 単数形の旧 API は削除したので、テストからは実運用の複数形 API を直接叩く。
# English: The singular legacy API is gone, so drive the plural production API directly.
def choose_web_search_image(user_question, result):
    selections = choose_web_search_images(user_question, result)
    return selections[0] if selections else None


# 単一の選択結果を複数形 API の形式 (リスト) に包んで渡すテスト用アダプタ。
# Test adapter that wraps a single selection into the list form the plural API expects.
def append_web_search_image_part(parts, selection, *, fallback_text=""):
    return append_web_search_image_parts(
        parts,
        [selection] if selection else None,
        fallback_text=fallback_text,
    )


# 画像候補を 9 件持つ 1 ソースの検索結果を作る。ロゴ (logo.svg) と空枠素材 (noimage.png) をわざと混ぜてある。
# Builds a one-source search result with nine image candidates, deliberately including a logo (logo.svg) and a placeholder (noimage.png).
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
                    WebSearchImageCandidate(
                        url="https://example.com/images/temple.jpg",
                        alt="古寺の紅葉",
                        kind="img",
                    ),
                    WebSearchImageCandidate(
                        url="https://example.com/images/garden.jpg",
                        alt="庭園の紅葉",
                        kind="img",
                    ),
                    WebSearchImageCandidate(
                        url="https://example.com/images/street.jpg",
                        alt="京都の街並み",
                        kind="img",
                    ),
                    WebSearchImageCandidate(
                        url="https://example.com/images/river.jpg",
                        alt="川沿いの紅葉",
                        kind="img",
                    ),
                    WebSearchImageCandidate(
                        url="https://example.com/images/park.jpg",
                        alt="公園の紅葉",
                        kind="img",
                    ),
                ),
            ),
        ),
    )


# URL の文字列だけで、プレースホルダやロゴ・アイコンなど写真ではない画像を判定する関数のテスト。
# Tests for the URL-only check that rejects non-photo images such as placeholders, logos and icons.
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


# 選定 LLM (get_llm_json_response) をモックし、プロンプトの内容、応答の解釈、回答パーツへの挿入結果を確かめる。
# Mocks the selection LLM (get_llm_json_response) and checks the prompt content, response parsing and the resulting answer parts.
class WebSearchImageSelectionTestCase(unittest.TestCase):
    # LLM が選んだ画像の URL・代替テキスト・出典・配置が選択結果に反映され、選定プロンプトに必要な指示が入っていること。
    # The chosen image's URL, alt text, source and placement appear in the selection,
    # and the selection prompt carries the required instructions.
    def test_llm_can_select_one_relevant_image(self):
        with patch(
            "services.web_search_images.get_llm_json_response",
            return_value=(
                '{"show_image": true, "image_id": "image-1", '
                '"alt_text": "嵐山の紅葉風景", '
                '"placements": {"image-1": {"position": "after_subject", "anchor": "嵐山"}}, '
                '"reason": "景観の説明に役立つ"}'
            ),
        ) as mock_llm:
            selection = choose_web_search_image(
                "京都の紅葉名所を画像付きで教えて",
                _result(),
            )

        self.assertEqual(
            selection,
            {
                "url": "https://example.com/images/maple.jpg",
                "alt": "嵐山の紅葉風景",
                "source_url": "https://example.com/kyoto",
                "source_title": "京都の紅葉ガイド",
                "placement": "after_subject",
                "placement_anchor": "嵐山",
            },
        )
        prompt = mock_llm.call_args.args[0][1]["content"]
        self.assertIn("image-1", prompt)
        self.assertIn("image-2", prompt)
        system_prompt = mock_llm.call_args.args[0][0]["content"]
        self.assertIn("This is an LLM placement plan", system_prompt)
        self.assertIn("after_subject", system_prompt)
        self.assertIn("do not leave the application to infer an anchor", system_prompt)
        # 生成UIとの排他はコード側で保証するため、画像選択のプロンプトには生成UIの記述を置かない。
        # Exclusivity with Generative UI is enforced in code, so the selector prompt never mentions it.
        self.assertNotIn("generated UI", system_prompt)
        self.assertIn("places and travel destinations", system_prompt)
        self.assertIn("programming, legal explanations", system_prompt)
        self.assertIn("Relevance is the highest priority", system_prompt)
        self.assertIn("sufficient quality", system_prompt)
        self.assertIn("non-duplication", system_prompt)
        self.assertIn("large watermarks", system_prompt)
        self.assertIn("any language or script", system_prompt)
        self.assertEqual(mock_llm.call_args.args[1], LIGHTWEIGHT_TASK_MODEL)
        self.assertEqual(
            mock_llm.call_args.kwargs["reasoning_effort"],
            LIGHTWEIGHT_TASK_REASONING_EFFORT,
        )
        self.assertEqual(
            mock_llm.call_args.kwargs["reasoning_format"],
            IMAGE_SELECTION_REASONING_FORMAT,
        )

    # LLM が 6 件選んでも採用は 5 件までで、代替テキストの指定が無い画像は候補側の alt を使う。
    # Even if the LLM picks six, only five are used, and an image with no alt text from the LLM keeps the candidate's own alt.
    def test_llm_can_select_up_to_five_relevant_images(self):
        with patch(
            "services.web_search_images.get_llm_json_response",
            return_value=(
                '{"show_image": true, "image_ids": '
                '["image-1", "image-2", "image-3", "image-4", "image-5", "image-6"], '
                '"alt_texts": {"image-1": "嵐山", "image-3": "古寺"}}'
            ),
        ):
            selections = choose_web_search_images(
                "京都の紅葉を画像付きで教えて",
                _result(),
            )

        self.assertEqual(len(selections), 5)
        self.assertEqual(
            [selection["url"] for selection in selections],
            [
                "https://example.com/images/maple.jpg",
                "https://example.com/images/togetsukyo.jpg",
                "https://example.com/images/temple.jpg",
                "https://example.com/images/garden.jpg",
                "https://example.com/images/street.jpg",
            ],
        )
        self.assertEqual(selections[0]["alt"], "嵐山")
        self.assertEqual(selections[2]["alt"], "古寺")
        self.assertEqual(selections[1]["alt"], "渡月橋の紅葉")

    # 日本語: 中国語の選定応答で真偽値や画像IDが文字列になっても、適切な画像を表示できることを検証します。
    # English: Verify a Chinese selection response still renders an image when flags and IDs are strings.
    def test_llm_can_select_image_from_localized_string_response(self):
        with patch(
            "services.web_search_images.get_llm_json_response",
            return_value=(
                '{"show_image": "是", "image_ids": "image-1", '
                '"alt_texts": {"image-1": "北京故宫的照片"}}'
            ),
        ):
            selections = choose_web_search_images(
                "请展示北京故宫的照片",
                _result(),
            )

        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0]["url"], "https://example.com/images/maple.jpg")
        self.assertEqual(selections[0]["alt"], "北京故宫的照片")

    def test_placeholder_and_site_furniture_candidates_never_reach_the_llm(self):
        # 空の枠になる素材（noimage 等）とロゴは、選定LLMへ渡す前に落とす。
        # Assets that render as an empty frame and site logos are dropped before
        # the selection LLM ever sees them.
        with patch(
            "services.web_search_images.get_llm_json_response",
            return_value='{"show_image": false, "image_id": "", "alt_text": ""}',
        ) as mock_llm:
            choose_web_search_image(
                "京都の紅葉名所を教えて",
                _result(),
            )

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
            choose_web_search_image(
                "京都の紅葉名所を教えて",
                _result(),
            )

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
            self.assertIsNone(
                choose_web_search_image(
                    "京都の紅葉の見頃を教えて",
                    _result(),
                )
            )

    # 候補に無い画像 ID が返されても表示しない (LLM の出力を信用しきらない)。
    # An image id that is not among the candidates is never rendered (the LLM output is not trusted blindly).
    def test_unknown_candidate_id_is_never_rendered(self):
        with patch(
            "services.web_search_images.get_llm_json_response",
            return_value='{"show_image": true, "image_id": "image-99", "alt_text": "x"}',
        ):
            self.assertIsNone(
                choose_web_search_image(
                    "画像を見せて",
                    _result(),
                )
            )

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

    def test_inserts_images_after_matching_subjects(self):
        selections = [
            {
                "url": "https://example.com/meigetsu.jpg",
                "alt": "明月院の写真",
                "source_url": "https://example.com/meigetsu",
                "placement": "after_subject",
                "placement_anchor": "明月院",
            },
            {
                "url": "https://example.com/tokeiji.jpg",
                "alt": "東慶寺の写真",
                "source_url": "https://example.com/tokeiji",
                "placement": "after_subject",
                "placement_anchor": "東慶寺",
            },
        ]

        parts = append_web_search_image_parts(
            [{"type": "text", "text": "明月院 説明です。東慶寺 説明です。"}],
            selections,
        )

        self.assertEqual(
            [part["type"] for part in parts],
            ["text", "web_search_image", "text", "web_search_image", "text"],
        )
        self.assertEqual(parts[0]["text"], "明月院")
        self.assertEqual(parts[2]["text"], " 説明です。東慶寺")
        self.assertEqual(parts[4]["text"], " 説明です。")

    # ストリーミング中は、LLM が指定したアンカー (明月院) の直後の文字位置で画像を出す。戻り値は (文字位置, 画像の番号)。
    # While streaming, the image is revealed right after the LLM-specified anchor (明月院). The return value is (text offset, image index).
    def test_streaming_reveals_an_image_at_the_llm_planned_boundary(self):
        images = build_web_search_image_parts(
            [
                {
                    "url": "https://example.com/meigetsu.jpg",
                    "alt": "明月院の写真",
                    "source_url": "https://example.com/meigetsu",
                    "placement": "after_subject",
                    "placement_anchor": "明月院",
                }
            ]
        )

        self.assertEqual(
            find_next_streaming_image_insertion("明月院", images),
            (3, 0),
        )

    # アンカーの指定が無い場合に、画像の alt などから配置先を推測しない (文頭を既定の位置にする)。
    # With no anchor specified, the placement is not inferred from image metadata such as alt text (the start of the answer is the default).
    def test_backend_does_not_infer_a_subject_from_image_metadata(self):
        images = build_web_search_image_parts(
            [
                {
                    "url": "https://example.com/meigetsu.jpg",
                    "alt": "明月院の写真",
                    "source_url": "https://example.com/meigetsu",
                }
            ]
        )

        self.assertEqual(
            find_next_streaming_image_insertion("明月院", images),
            (0, 0),
        )

    # 同じ URL は重複させず、画像は最大 5 件まで追加する。
    # Duplicate URLs are collapsed and at most five images are appended.
    def test_appends_up_to_five_images_and_deduplicates_urls(self):
        selections = [
            {
                "url": f"https://example.com/images/selected-{index}.jpg",
                "alt": f"画像{index}",
                "source_url": "https://example.com/article",
            }
            for index in range(1, 7)
        ]
        parts = append_web_search_image_parts(
            [{"type": "text", "text": "回答"}],
            [selections[0], *selections, selections[1]],
        )

        self.assertIsNotNone(parts)
        assert parts is not None
        image_parts = [part for part in parts if part["type"] == "web_search_image"]
        self.assertEqual(len(image_parts), 5)
        self.assertEqual(
            [part["image"]["url"] for part in image_parts],
            [selection["url"] for selection in selections[:5]],
        )

    def test_preserves_existing_images_when_adding_more_selections(self):
        existing_image = {
            "type": "web_search_image",
            "image": {
                "url": "https://example.com/images/existing.jpg",
                "alt": "明月院の写真",
                "source_url": "https://example.com/meigetsu",
            },
            "_placement": "after_subject",
            "_placement_anchor": "明月院",
        }
        parts = append_web_search_image_parts(
            [{"type": "text", "text": "明月院と東慶寺を紹介します。"}, existing_image],
            {
                "url": "https://example.com/images/new.jpg",
                "alt": "東慶寺の写真",
                "source_url": "https://example.com/tokeiji",
                "placement": "after_subject",
                "placement_anchor": "東慶寺",
            },
        )

        self.assertEqual(
            [part["type"] for part in parts],
            ["text", "web_search_image", "text", "web_search_image", "text"],
        )
        self.assertEqual(parts[1]["image"]["url"], existing_image["image"]["url"])
        self.assertEqual(parts[3]["image"]["url"], "https://example.com/images/new.jpg")

    # 回答に生成UI (sandbox_artifact) が含まれるときは画像を足さない。
    # No image is added when the answer already contains a generated UI (sandbox_artifact).
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

    # javascript: など http(s) 以外の URL は画像として採用しない。
    # URLs that are not http(s), such as javascript:, are not accepted as images.
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
