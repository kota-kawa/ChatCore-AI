"""判断ステップの下書き判定器（AnswerDraftFilter）の規則を検証する。

Verifies the rules of the decision-step draft filter (AnswerDraftFilter).
"""

import unittest

from services.chat_answer_draft import DRAFT_MIN_VISIBLE_CHARS, AnswerDraftFilter
from services.chat_turn_state import TURN_STATE_UPDATE_CLOSE_TAG, TURN_STATE_UPDATE_OPEN_TAG
from services.llm_protocol_leak import strip_leaked_reasoning_chunks

ENVELOPE = (
    f'{TURN_STATE_UPDATE_OPEN_TAG}{{"objective":"説明する","unresolved_questions":[],'
    f'"facts":[],"evidence_ids":[],"ready_to_answer":true}}{TURN_STATE_UPDATE_CLOSE_TAG}'
)
# 保留の閾値を超える長さの本文。
# A body long enough to pass the hold-back threshold.
LONG_BODY = "これは下書きとして先に見せてよい十分に長い回答の書き出しです。"


def feed_all(draft, chunks):
    """Feed chunks and return (drafted text after resets, number of resets)."""
    shown = ""
    resets = 0
    for chunk in chunks:
        update = draft.feed(chunk)
        if update.reset:
            shown = ""
            resets += 1
        shown += update.text
    return shown, resets


class AnswerDraftFilterTestCase(unittest.TestCase):
    # 日本語: 見える文字が閾値に達するまでは何も出さず、達した時点でそれまでをまとめて出すことを検証します。
    # English: Nothing is drafted until the visible characters reach the threshold; then the held text is released at once.
    def test_holds_back_until_enough_visible_characters(self):
        draft = AnswerDraftFilter()
        self.assertGreater(len(LONG_BODY), DRAFT_MIN_VISIBLE_CHARS)

        first = draft.feed("  " + LONG_BODY[:5])
        second = draft.feed(LONG_BODY[5:])
        third = draft.feed("続きです。")

        self.assertEqual(first.text, "")
        self.assertEqual(second.text, LONG_BODY)
        self.assertEqual(third.text, "続きです。")
        self.assertFalse(any(update.reset for update in (first, second, third)))

    # 日本語: 閾値に届かないままストリームが終わった場合は下書きが出ないことを検証します（確定でまとめて出る）。
    # English: A stream that ends below the threshold drafts nothing; confirmation delivers it in one go.
    def test_short_stream_never_drafts(self):
        shown, resets = feed_all(AnswerDraftFilter(), ["はい。", "了解です。"])

        self.assertEqual(shown, "")
        self.assertEqual(resets, 0)

    # 日本語: 封筒は本文に混ぜず、チャンクをまたぐ封筒も除いて、その後ろの本文から下書きすることを検証します。
    # English: An envelope never leaks into the draft, even split across chunks, and drafting starts at the body behind it.
    def test_envelope_before_body_is_removed_even_when_split(self):
        for split_at in (5, 30, len(ENVELOPE) - 3):
            with self.subTest(split_at=split_at):
                shown, resets = feed_all(
                    AnswerDraftFilter(),
                    [ENVELOPE[:split_at], ENVELOPE[split_at:], LONG_BODY],
                )

                self.assertEqual(shown, LONG_BODY)
                self.assertEqual(resets, 0)

    # 日本語: 本文のあとに封筒が付いても、封筒の部分は下書きへ出さないことを検証します。
    # English: An envelope following the body is not drafted either.
    def test_envelope_after_body_is_removed(self):
        shown, _resets = feed_all(AnswerDraftFilter(), [LONG_BODY, ENVELOPE])

        self.assertEqual(shown, LONG_BODY)

    # 日本語: 先頭が `{` のステップ（タグ無しの封筒の可能性）は下書きしないことを検証します。
    # English: A step opening with `{` (a possibly untagged envelope) is not drafted.
    def test_bare_json_opening_is_not_drafted(self):
        body = '{"objective":"説明する","unresolved_questions":[],"ready_to_answer":true}'
        shown, resets = feed_all(AnswerDraftFilter(), ["\n", body[:10], body[10:], "さらに文章が続いても出さない。" * 3])

        self.assertEqual(shown, "")
        self.assertEqual(resets, 0)

    # 日本語: コードフェンス付き JSON で始まるステップも下書きしないことを検証します。
    # English: A step opening with a fenced JSON is not drafted.
    def test_fenced_json_opening_is_not_drafted(self):
        for opening in ("```json\n{", "```\n{", "```JSON\n  {"):
            with self.subTest(opening=opening):
                shown, _resets = feed_all(AnswerDraftFilter(), [opening, '"objective":"説明する","ready_to_answer":true}\n```'])

                self.assertEqual(shown, "")

    # 日本語: JSON 以外のコードフェンスで始まる回答は下書きしてよいことを検証します。
    # English: An answer opening with a non-JSON code fence may be drafted.
    def test_non_json_fence_opening_is_drafted(self):
        body = "```python\nprint('これは十分に長いサンプルコードです')\n```"
        shown, _resets = feed_all(AnswerDraftFilter(), [body])

        self.assertEqual(shown, body)

    # 日本語: `</think>` が現れたらそれまでの下書きを取り消し、その後ろから再開し、確定時の除去結果と一致することを検証します。
    # English: A `</think>` discards the draft so far and restarts behind it, matching what confirmation keeps.
    def test_reasoning_close_tag_resets_and_resumes_after_it(self):
        reasoning = "ユーザーは挨拶を求めているので、丁寧に答える方針で考えます。"
        answer = "こんにちは。今日はどのようなご用件でしょうか。何でもお尋ねください。"
        chunks = [reasoning, "\n</thi", "nk>\n\n", answer[:10], answer[10:]]

        draft = AnswerDraftFilter()
        updates = [draft.feed(chunk) for chunk in chunks]

        self.assertEqual(updates[0].text, reasoning)
        self.assertEqual([update.reset for update in updates], [False, False, True, False, False])
        shown, _resets = feed_all(AnswerDraftFilter(), chunks)
        confirmed = "".join(strip_leaked_reasoning_chunks(chunks))
        self.assertEqual(shown, confirmed)
        self.assertEqual(shown, answer)

    # 日本語: 閉じタグの後ろも閾値で保留し直すことを検証します（短い後続は出さない）。
    # English: Text behind the closing tag is held back by the threshold again.
    def test_text_after_reasoning_close_tag_is_held_again(self):
        draft = AnswerDraftFilter()
        draft.feed(LONG_BODY)
        update = draft.feed("</think>短い答え")

        self.assertTrue(update.reset)
        self.assertEqual(update.text, "")

    # 日本語: 何も見せていなければ、閉じタグがあってもリセットを要求しないことを検証します。
    # English: With nothing shown yet, a closing tag does not request a discard.
    def test_reasoning_close_tag_before_anything_shown_does_not_reset(self):
        update = AnswerDraftFilter().feed("短い下書き</think>" + LONG_BODY)

        self.assertFalse(update.reset)
        self.assertEqual(update.text, LONG_BODY)

    # 日本語: コードの中の `</think>` は無視し、リセットしないことを検証します。
    # English: A `</think>` inside code is ignored and does not reset.
    def test_reasoning_close_tag_inside_code_is_ignored(self):
        body = "タグの書き方の例です。\n```html\n<think>x</think>\n```\nこのように書きます。"
        shown, resets = feed_all(AnswerDraftFilter(), [body[:20], body[20:]])

        self.assertEqual(shown, body)
        self.assertEqual(resets, 0)

    # 日本語: 利用者がタグ自体を話題にしているときは、本文中の閉じタグでもリセットしないことを検証します。
    # English: When the user is asking about the tag itself, a closing tag in the body does not reset.
    def test_reasoning_close_tag_is_kept_when_user_mentions_it(self):
        body = "閉じタグは </think> と書きます。これが求められた回答の本文です。"
        shown, resets = feed_all(AnswerDraftFilter("</think> とは何ですか"), [body])

        self.assertEqual(shown, body)
        self.assertEqual(resets, 0)

    # 日本語: 引用マーカーは下書きから除き、チャンクをまたぐマーカーは完結するまで保留することを検証します。
    # English: Citation markers are removed from the draft, and a marker split across chunks waits until it is complete.
    def test_citation_markers_are_removed_and_partial_ones_held(self):
        marker = "[[source:src_0123456789abcdef0123]]"
        draft = AnswerDraftFilter()
        updates = [
            draft.feed(LONG_BODY + "根拠は"),
            draft.feed("[[source:src_0123"),
            draft.feed("456789abcdef0123]]"),
            draft.feed("です。"),
        ]

        self.assertEqual(updates[0].text, LONG_BODY + "根拠は")
        self.assertEqual(updates[1].text, "")
        self.assertEqual(updates[2].text, "")
        self.assertEqual(updates[3].text, "です。")
        self.assertNotIn(marker, "".join(update.text for update in updates))

    # 日本語: モデルが書いた引用チップの HTML も下書きから除くことを検証します。
    # English: Citation chip HTML echoed by the model is removed from the draft too.
    def test_citation_chip_html_is_removed(self):
        chip = '<a class="web-search-citation" href="https://example.com">1</a>'
        shown, _resets = feed_all(AnswerDraftFilter(), [LONG_BODY, chip, "続き。"])

        self.assertEqual(shown, LONG_BODY + "続き。")


if __name__ == "__main__":
    unittest.main()
