"""本文に漏れた内部のツール呼び出し形式と推論の下書きを取り除く処理を検証する（issue #771）。

Verifies removal of internal tool-call protocol and reasoning drafts leaking into body text (issue #771).
"""

import unittest

from services.llm_protocol_leak import ProtocolLeakGuard, find_protocol_leak, strip_leaked_reasoning_chunks


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
            "- 未決事項: 無料枠\n</parameter>\n</function>": "- 未決事項: 無料枠\n",
            "回答です。<tool_call>\n<function=web_search>": "回答です。",
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
    def test_never_releases_the_head_of_a_marker_split_across_chunks(self):
        # 逐次配信では渡した文字を取り消せないので、目印の頭が先に出てはいけない（issue #778）。
        # A streamed character cannot be retracted, so a marker head must never go out early (issue #778).
        answer = "回答です。\n"
        for chunks in (
            [answer + "<|im_", "end|>続き"],
            [answer + "</assis", "tant>"],
            [answer + "liassis", "tant to=functions.web_search"],
            [answer + "liassistant", " to=functions.web_search"],
            [answer + "liassistant to=fun", "ctions.web_search\n{}"],
            [answer + "multi_tool_", "use.parallel {}"],
        ):
            with self.subTest(chunks=chunks):
                guard = ProtocolLeakGuard()
                self.assertEqual(guard.feed(chunks[0]), answer)
                self.assertEqual(guard.feed(chunks[1]), "")
                self.assertTrue(guard.tripped)
                self.assertEqual(guard.overflow_chars, 0)

    def test_holds_only_a_possible_marker_head_and_releases_it_with_the_next_chunk(self):
        guard = ProtocolLeakGuard()
        self.assertEqual(guard.feed("関数 to= の説明です。"), "関数 to= の説明です。")
        # ` to=functions` の頭になりうる `t` は、前の1語ごと保留する。
        # A `t` that could open ` to=functions` is held together with the word before it.
        self.assertEqual(guard.feed("I want t"), "I ")
        self.assertEqual(guard.feed("o go. <b"), "want to go. ")
        self.assertEqual(guard.feed(">太字</b>"), "<b>太字</b>")
        self.assertEqual(guard.feed("That was"), "That ")
        self.assertEqual(guard.flush(), "was")
        self.assertFalse(guard.tripped)

    def test_cuts_inside_a_single_chunk(self):
        guard = ProtocolLeakGuard()
        self.assertEqual(guard.feed("156<|im_end|>156"), "156")
        self.assertTrue(guard.tripped)
        self.assertEqual(guard.overflow_chars, 0)
        self.assertEqual(guard.flush(), "")

    def test_reports_released_text_the_hold_back_could_not_foresee(self):
        # 役割名の崩れ方は予測しきれない。すでに渡した頭は、取り消すべき長さとして返す。
        # Garbled role words cannot all be foreseen; a head already released is reported for retraction.
        guard = ProtocolLeakGuard()
        self.assertEqual(guard.feed("回答\nxyz"), "回答\nxyz")
        self.assertEqual(guard.feed(" to=functions.web_search"), "")
        self.assertTrue(guard.tripped)
        self.assertEqual(guard.overflow_chars, len("xyz"))


class StripLeakedReasoningChunksTestCase(unittest.TestCase):
    def test_drops_the_draft_before_the_closing_tag_and_keeps_answer_boundaries(self):
        # 実 API で観測した形: 開始タグの無い下書き、空行、閉じタグ、回答の順。
        # The shape observed against the real API: an unopened draft, blank lines, the closing tag, the answer.
        chunks = ["はい、クラウドで", "大丈夫です。\n\n\n</thi", "nk>\n\nはい、", "クラウドで大丈夫です。"]
        self.assertEqual(strip_leaked_reasoning_chunks(chunks), ["はい、", "クラウドで大丈夫です。"])

    def test_uses_the_last_closing_tag_and_drops_a_tagged_block_too(self):
        self.assertEqual(strip_leaked_reasoning_chunks(["<think>案A</think>案B</think>", "\n回答"]), ["回答"])

    def test_returns_text_without_a_closing_tag_unchanged(self):
        chunks = ["下書きではない", "ふつうの回答です。"]
        self.assertEqual(strip_leaked_reasoning_chunks(chunks), chunks)

    def test_keeps_a_tag_the_answer_shows_as_code_or_the_user_asked_about(self):
        in_code = ["閉じタグは `</think>` です。", "\n```\n<think>…</think>\n```"]
        self.assertEqual(strip_leaked_reasoning_chunks(in_code), in_code)
        asked = ["推論は </think> で終わります。"]
        self.assertEqual(strip_leaked_reasoning_chunks(asked, "</THINK> タグって何？"), asked)

    def test_keeps_the_indentation_of_an_answer_that_starts_with_an_indented_block(self):
        self.assertEqual(strip_leaked_reasoning_chunks(["下書き</think>\n \n", "    code()\n"]), ["    code()\n"])

    def test_an_answer_that_is_only_a_draft_becomes_empty(self):
        self.assertEqual(strip_leaked_reasoning_chunks(["下書きだけ\n</think>\n"]), [])


if __name__ == "__main__":
    unittest.main()
