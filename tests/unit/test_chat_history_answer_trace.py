"""保存済みの回答を読み出すとき、実行記録（「回答までのステップ」）が本文と別のパーツとして渡ることのテスト。
構造化前に保存された回答（記録の HTML が本文の先頭にある）と、構造化後の回答の両方を、表示用とモデル用の整形で確かめる。

Tests that reading a stored answer hands over the execution record (the "steps to the answer") as a part separate
from the body. Covers answers saved before structuring (record markup at the head of the body) and after it, in
both the display form and the form replayed to the model.
"""

import unittest
from unittest.mock import MagicMock

from services.chat_context import normalize_message_text
from services.repositories.chat_repository import ChatRepository
from tests.helpers.answer_trace_fixtures import load_answer_trace, load_legacy_answer_trace_html

_IMAGE_PART = {
    "type": "web_search_image",
    "image": {
        "url": "https://cdn.example.com/hero.jpg",
        "alt": "写真",
        "source_url": "https://example.com/article",
    },
}


def _node(message, *, sender="assistant", message_parts=None):
    return {
        "id": 1,
        "parent_id": None,
        "message": message,
        "sender": sender,
        "timestamp": None,
        "message_parts": message_parts,
    }


def _display_entry(node):
    return ChatRepository(MagicMock())._serialize_path_node(node, {None: [1]})


class StoredAnswerTraceReadTestCase(unittest.TestCase):
    def setUp(self):
        self.legacy_html = load_legacy_answer_trace_html("full")
        self.legacy_part = {"type": "legacy_answer_trace", "html": self.legacy_html}

    # 日本語: 構造化前に保存された本文だけの回答が、表示用では本文と記録のパーツに分かれることを検証します。
    # English: Verify a body-only answer saved before structuring is split into body and record part for display.
    def test_legacy_answer_is_split_for_display(self):
        entry = _display_entry(_node(f"{self.legacy_html}\n\n本文です。"))

        self.assertEqual(entry["message"], "本文です。")
        self.assertEqual(entry["message_parts"], [self.legacy_part, {"type": "text", "text": "本文です。"}])

    # 日本語: 旧形式で記録より前に保存されていた画像は、記録の後ろに並ぶことを検証します。
    # English: Verify an image saved ahead of the record in the legacy shape ends up after the record.
    def test_legacy_answer_with_parts_keeps_the_image_after_the_record(self):
        text = f"{self.legacy_html}\n\n本文です。"

        entry = _display_entry(_node(text, message_parts=[_IMAGE_PART, {"type": "text", "text": text}]))

        self.assertEqual(entry["message"], "本文です。")
        self.assertEqual(
            entry["message_parts"],
            [self.legacy_part, _IMAGE_PART, {"type": "text", "text": "本文です。"}],
        )

    # 日本語: モデルへ戻す履歴の本文には、構造化前の記録の HTML が含まれないことを検証します。
    # English: Verify the body replayed to the model carries none of the pre-structuring record markup.
    def test_legacy_answer_is_replayed_to_the_model_without_the_record(self):
        (message,) = ChatRepository._path_to_llm_messages([_node(f"{self.legacy_html}\n\n本文です。")])

        self.assertEqual(message["role"], "assistant")
        self.assertEqual(message["content"], "本文です。")
        self.assertEqual(normalize_message_text(message["content"]), "本文です。")

    # 日本語: 構造化後の回答は、本文をそのまま、記録を先頭のパーツとして渡すことを検証します。
    # English: Verify a structured answer hands over its body as is and the record as the leading part.
    def test_structured_answer_keeps_its_body_and_leads_with_the_record(self):
        trace_part = {"type": "answer_trace", "trace": load_answer_trace("full")}
        node = _node("本文です。", message_parts=[trace_part, {"type": "text", "text": "本文です。"}])

        entry = _display_entry(node)
        (message,) = ChatRepository._path_to_llm_messages([node])

        self.assertEqual(entry["message"], "本文です。")
        self.assertEqual(entry["message_parts"], [trace_part, {"type": "text", "text": "本文です。"}])
        self.assertEqual(message["content"], "本文です。")

    # 日本語: 利用者の発話は、記録の HTML と同じ文字列で始まっていても書き換えないことを検証します。
    # English: Verify a user message is left untouched even when it starts with the same string as the record markup.
    def test_user_message_is_never_converted(self):
        text = f"{self.legacy_html}\n\nこの HTML は何ですか？"

        entry = _display_entry(_node(text, sender="user"))
        (message,) = ChatRepository._path_to_llm_messages([_node(text, sender="user")])

        self.assertEqual(entry["message"], text)
        self.assertNotIn("message_parts", entry)
        self.assertEqual(message["content"], text)


if __name__ == "__main__":
    unittest.main()
