"""メッセージパーツの表示順規約（実行記録とWeb検索画像の並び）と、旧形式の回答の読み出しを検証する。

Verifies the display-order contract of message parts (the execution record and web search images) and how
answers saved in the legacy shape are read.
"""

import unittest

from services.answer_trace import answer_trace_part
from services.message_parts_display import (
    normalize_message_parts_for_display,
    separate_legacy_answer_trace,
    strip_web_search_sources_html,
)
from tests.helpers.answer_trace_fixtures import load_answer_trace, load_legacy_answer_trace_html

IMAGE_PART = {
    "type": "web_search_image",
    "image": {
        "url": "https://cdn.example.com/hero.jpg",
        "alt": "写真",
        "source_url": "https://example.com/article",
    },
}


# 構造化前に保存された回答を、本文と実行記録のパーツへ分ける読み出しの変換を確かめる。
# Checks the read-time conversion that splits an answer saved before structuring into body and record part.
class SeparateLegacyAnswerTraceTestCase(unittest.TestCase):
    def setUp(self):
        # 出典を持つステップは、内側にも <details> を持つ。
        # Steps that carry sources nest a <details> of their own.
        self.trace = load_legacy_answer_trace_html("full")
        self.assertIn('<details class="web-search-sources__step-details">', self.trace)
        self.legacy_part = {"type": "legacy_answer_trace", "html": self.trace}

    def test_body_only_answer_becomes_a_record_part_and_a_text_part(self):
        message, parts = separate_legacy_answer_trace(f"{self.trace}\n\n本文です。", None)

        self.assertEqual(message, "本文です。")
        self.assertEqual(parts, [self.legacy_part, {"type": "text", "text": "本文です。"}])

    def test_the_record_is_removed_from_the_leading_text_part(self):
        text = f"{self.trace}\n\n本文です。"

        message, parts = separate_legacy_answer_trace(text, [{"type": "text", "text": text}])

        self.assertEqual(message, "本文です。")
        self.assertEqual(parts, [self.legacy_part, {"type": "text", "text": "本文です。"}])

    def test_an_image_saved_ahead_of_the_record_ends_up_after_it(self):
        text = f"{self.trace}\n\n本文です。"

        _, parts = separate_legacy_answer_trace(text, [IMAGE_PART, {"type": "text", "text": text}])

        self.assertEqual(parts, [self.legacy_part, IMAGE_PART, {"type": "text", "text": "本文です。"}])

    def test_a_text_part_holding_only_the_record_is_dropped(self):
        # 画像のある回答では、記録だけのテキストパーツに分けて保存していた。
        # Answers with images were saved with the record split into a text part of its own.
        parts = [{"type": "text", "text": self.trace}, IMAGE_PART, {"type": "text", "text": "本文です。"}]

        _, converted = separate_legacy_answer_trace(f"{self.trace}\n\n本文です。", parts)

        self.assertEqual(converted, [self.legacy_part, IMAGE_PART, {"type": "text", "text": "本文です。"}])

    def test_a_record_without_a_body_leaves_no_text_part(self):
        message, parts = separate_legacy_answer_trace(self.trace, None)

        self.assertEqual(message, "")
        self.assertEqual(parts, [self.legacy_part])

    def test_an_answer_without_a_leading_record_is_returned_unchanged(self):
        parts = [{"type": "text", "text": "本文だけの回答"}, IMAGE_PART]

        message, converted = separate_legacy_answer_trace("本文だけの回答", parts)

        self.assertEqual(message, "本文だけの回答")
        self.assertIs(converted, parts)
        self.assertEqual(separate_legacy_answer_trace("本文だけの回答", None), ("本文だけの回答", None))

    def test_markup_later_in_the_body_is_not_treated_as_the_record(self):
        text = f"本文です。\n\n{self.trace}"

        self.assertEqual(separate_legacy_answer_trace(text, None), (text, None))

    def test_converting_twice_changes_nothing(self):
        text = f"{self.trace}\n\n本文です。"
        message, parts = separate_legacy_answer_trace(text, [IMAGE_PART, {"type": "text", "text": text}])

        self.assertEqual(separate_legacy_answer_trace(message, parts), (message, parts))


# 画像の枚数上限と、実行記録・画像・本文の並びが冪等に整うことを確かめる。
# Checks the image cap and that record, image and text ordering is normalised idempotently.
class NormalizeMessagePartsForDisplayTestCase(unittest.TestCase):
    def setUp(self):
        self.trace_part = answer_trace_part(load_answer_trace("full"))

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

    def test_the_execution_record_is_placed_first(self):
        parts = [IMAGE_PART, {"type": "text", "text": "本文です。"}, self.trace_part]

        normalized = normalize_message_parts_for_display(parts)

        self.assertEqual(normalized, [self.trace_part, IMAGE_PART, {"type": "text", "text": "本文です。"}])

    def test_only_the_first_execution_record_is_kept(self):
        legacy_part = {"type": "legacy_answer_trace", "html": load_legacy_answer_trace_html("full")}

        normalized = normalize_message_parts_for_display(
            [{"type": "text", "text": "本文です。"}, self.trace_part, legacy_part]
        )

        self.assertEqual(normalized, [self.trace_part, {"type": "text", "text": "本文です。"}])

    def test_placement_is_idempotent(self):
        once = normalize_message_parts_for_display([IMAGE_PART, {"type": "text", "text": "本文です。"}, self.trace_part])

        self.assertEqual(normalize_message_parts_for_display(once), once)

    def test_inline_image_order_is_preserved_without_a_record(self):
        parts = [{"type": "text", "text": "本文です。"}, IMAGE_PART]

        normalized = normalize_message_parts_for_display(parts)

        self.assertEqual([part["type"] for part in normalized], ["text", "web_search_image"])

    def test_generated_ui_suppresses_the_image_and_keeps_the_record(self):
        parts = [
            IMAGE_PART,
            {"type": "text", "text": "本文です。"},
            {"type": "sandbox_artifact", "artifact": {"title": "図"}},
            self.trace_part,
        ]

        normalized = normalize_message_parts_for_display(parts)

        self.assertEqual([part["type"] for part in normalized], ["answer_trace", "text", "sandbox_artifact"])


# 日本語: Web 検索の表示ブロックを本文から取り除く処理を検証するテストクラス。
# English: Test class for stripping web-search display blocks out of prose.
class StripWebSearchSourcesHtmlTestCase(unittest.TestCase):
    # 日本語: 入れ子のステップ、旧形式の参照サイト一覧、単一引用符のクラス指定をすべて除き、本文と通常の details は残すことを検証します。
    # English: Verify nested steps, the legacy source list and single-quoted classes are all removed while prose and ordinary details stay.
    def test_strips_every_sources_block_and_keeps_other_markup(self):
        text = (
            '<details class="web-search-sources web-search-sources--trace"><summary>回答までのステップ</summary>'
            '<details class="web-search-sources__step-details"><summary>検索</summary>出典</details></details>\n\n'
            "本文です。<details><summary>補足</summary>残す</details>\n\n"
            "<details class='web-search-sources'><summary>参照したWebサイト</summary>一覧</details>"
        )

        self.assertEqual(
            strip_web_search_sources_html(text),
            "\n\n本文です。<details><summary>補足</summary>残す</details>\n\n",
        )
        self.assertEqual(strip_web_search_sources_html("本文のみ"), "本文のみ")


if __name__ == "__main__":
    unittest.main()
