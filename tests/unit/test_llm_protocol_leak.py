"""本文に漏れた内部のツール呼び出し形式を検出する処理を検証する（issue #771）。

Verifies detection of internal tool-call protocol leaking into body text (issue #771).
"""

import unittest

from services.llm_protocol_leak import ProtocolLeakGuard, find_protocol_leak


class FindProtocolLeakTestCase(unittest.TestCase):
    def test_finds_observed_leak_shapes(self):
        # 実 API で観測した漏れの形 / leak shapes observed against the real API
        cases = {
            'Test complete\nliassistant to=functions.web_search\n{"query":"x"}': "Test complete\n",
            'テスト完了\nmulti_tool_use.parallel {"tool_uses":[]}': "テスト完了\n",
            "テスト完了<|im_end|>\n\nテスト完了": "テスト完了",
            "Test complete\n<|assistant|>THOOK": "Test complete\n",
            "156 \n</|assistant|> \n16.0": "156 \n",
            "156\n</assistant> (analysis) code?": "156\n",
        }
        for text, kept in cases.items():
            with self.subTest(text=text):
                self.assertEqual(text[: find_protocol_leak(text)], kept)

    def test_ignores_ordinary_text_and_code_blocks(self):
        for text in (
            "関数 to= の説明です。functions は複数形です。",
            "ChatML では ```<|im_end|>``` で発話を区切ります。",
            "```\nassistant to=functions.web_search\n```\nこれは Harmony 形式の例です。",
            "ChatML では `<|im_end|>` で区切ります。",
            "GPT のトークンは `<|endoftext|>` です",
            "See `assistant to=functions.x` docs",
            # 生成途中でまだ閉じていないインラインコード / inline code not yet closed mid-stream
            "終端は `<|im_end|>",
        ):
            with self.subTest(text=text):
                self.assertIsNone(find_protocol_leak(text))


class ProtocolLeakGuardTestCase(unittest.TestCase):
    def test_keeps_text_before_a_marker_split_across_chunks(self):
        guard = ProtocolLeakGuard()
        self.assertEqual(guard.feed("回答です。\n<|im_"), "回答です。\n<|im_")
        self.assertFalse(guard.tripped)
        self.assertEqual(guard.feed("end|>続き"), "")
        self.assertTrue(guard.tripped)
        # 目印の頭 `<|im_` はすでに前のチャンクで渡しているので、その分を取り消させる。
        # The marker head `<|im_` went out with the previous chunk, so that much must be retracted.
        self.assertEqual(guard.overflow_chars, len("<|im_"))
        self.assertEqual(guard.feed("さらに"), "")

    def test_cuts_inside_a_single_chunk(self):
        guard = ProtocolLeakGuard()
        self.assertEqual(guard.feed("156<|im_end|>156"), "156")
        self.assertTrue(guard.tripped)
        self.assertEqual(guard.overflow_chars, 0)


if __name__ == "__main__":
    unittest.main()
