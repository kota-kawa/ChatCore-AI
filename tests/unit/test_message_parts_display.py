"""メッセージパーツの表示順規約（回答トレースとWeb検索画像の並び）を検証する。"""

import unittest

from services.message_parts_display import (
    apply_visual_part_contract,
    normalize_message_parts_for_display,
    split_answer_trace_block,
)
from services.web_search import WebSearchResult, WebSearchSource
from services.web_search_trace import (
    answer_step,
    build_web_search_trace_markdown,
    search_step,
)

IMAGE_PART = {
    "type": "web_search_image",
    "image": {
        "url": "https://cdn.example.com/hero.jpg",
        "alt": "写真",
        "source_url": "https://example.com/article",
    },
}


def _trace_markdown(*, with_sources: bool = False) -> str:
    if not with_sources:
        return build_web_search_trace_markdown(
            steps=[{"title": "検索が必要か判断", "detail": "最新情報が必要でした。"}]
        )
    result = WebSearchResult(
        query="鎌倉 紅葉",
        searched_at="2026-04-30T00:00:00+00:00",
        sources=(
            WebSearchSource(
                url="https://example.com/article",
                title="記事",
                hostname="example.com",
                age="",
                snippets=("抜粋",),
                page_text="本文",
            ),
        ),
    )
    return build_web_search_trace_markdown(
        result, steps=[search_step(result), answer_step([result])]
    )


class SplitAnswerTraceBlockTestCase(unittest.TestCase):
    def test_splits_the_trace_block_off_the_answer_text(self):
        trace = _trace_markdown()

        block, remainder = split_answer_trace_block(f"{trace}\n\n本文です。")

        self.assertEqual(block, trace)
        self.assertEqual(remainder, "本文です。")

    def test_keeps_nested_step_details_inside_the_trace_block(self):
        trace = _trace_markdown(with_sources=True)
        self.assertIn('<details class="web-search-sources__step-details">', trace)

        block, remainder = split_answer_trace_block(f"{trace}\n\n本文です。")

        self.assertEqual(block, trace)
        self.assertEqual(remainder, "本文です。")

    def test_text_without_a_trace_block_is_returned_unchanged(self):
        block, remainder = split_answer_trace_block("本文だけの回答")

        self.assertEqual(block, "")
        self.assertEqual(remainder, "本文だけの回答")


class NormalizeMessagePartsForDisplayTestCase(unittest.TestCase):
    def test_at_most_five_images_are_retained_per_reply(self):
        images = [
            {
                **IMAGE_PART,
                "image": {
                    **IMAGE_PART["image"],
                    "url": f"https://cdn.example.com/hero-{index}.jpg",
                },
            }
            for index in range(1, 7)
        ]

        normalized = normalize_message_parts_for_display(
            [{"type": "text", "text": "本文です。"}, *images]
        )

        self.assertEqual(
            len([part for part in normalized if part["type"] == "web_search_image"]),
            5,
        )

    def test_legacy_leading_image_is_placed_below_the_answer_trace(self):
        trace = _trace_markdown()
        parts = [IMAGE_PART, {"type": "text", "text": f"{trace}\n\n本文です。"}]

        normalized = normalize_message_parts_for_display(parts)

        self.assertEqual(
            [part["type"] for part in normalized],
            ["text", "web_search_image", "text"],
        )
        self.assertEqual(normalized[0]["text"], trace)
        self.assertEqual(normalized[2]["text"], "本文です。")

    def test_placement_is_idempotent(self):
        trace = _trace_markdown()
        parts = [IMAGE_PART, {"type": "text", "text": f"{trace}\n\n本文です。"}]

        once = normalize_message_parts_for_display(parts)

        self.assertEqual(normalize_message_parts_for_display(once), once)

    def test_legacy_trace_only_answer_keeps_the_image_below_the_trace(self):
        trace = _trace_markdown()
        parts = [{"type": "text", "text": trace}, IMAGE_PART]

        normalized = normalize_message_parts_for_display(parts)

        self.assertEqual([part["type"] for part in normalized], ["text", "web_search_image"])
        self.assertEqual(normalized[0]["text"], trace)

    def test_inline_image_order_is_preserved_without_a_trace(self):
        parts = [{"type": "text", "text": "本文です。"}, IMAGE_PART]

        normalized = normalize_message_parts_for_display(parts)

        self.assertEqual([part["type"] for part in normalized], ["text", "web_search_image"])

    def test_generated_ui_suppresses_the_image(self):
        trace = _trace_markdown()
        parts = [
            IMAGE_PART,
            {"type": "text", "text": f"{trace}\n\n本文です。"},
            {"type": "sandbox_artifact", "artifact": {"title": "図"}},
        ]

        normalized = normalize_message_parts_for_display(parts)

        self.assertEqual([part["type"] for part in normalized], ["text", "sandbox_artifact"])
        self.assertEqual(normalized[0]["text"], f"{trace}\n\n本文です。")


class ApplyVisualPartContractTestCase(unittest.TestCase):
    def test_contract_does_not_split_the_trace_block(self):
        # 引用解決が本文テキストを書き戻す前段では、テキストパートを分割しない。
        # The mid-pipeline contract must keep one text part so citation
        # resolution can rewrite the answer text safely.
        trace = _trace_markdown()
        text_part = {"type": "text", "text": f"{trace}\n\n本文です。"}

        contracted = apply_visual_part_contract([text_part, IMAGE_PART])

        self.assertEqual(contracted, [text_part, IMAGE_PART])


if __name__ == "__main__":
    unittest.main()
