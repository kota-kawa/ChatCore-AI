"""判断ステップの本文を、確定前に表示専用の下書きとして先に見せるための判定器。

Decides which part of a decision step's body can be shown early as a display-only draft.

判断ステップの本文は、ツール呼び出しで終わらないと分かるまで保存も配信もされない（ADR 0006）。
その間に画面へ最初の文字を出すため、確定とは別に下書きを流す。下書きは保存せず、確定時に
`answer_draft_reset` で捨てて確定した本文に置き換える。ここは I/O を持たない純粋な状態機械で、
流してよい差分と、見せた下書きを捨てるべきかだけを返す。
A decision step's body is neither saved nor published until the step is known not to end in a tool
call (ADR 0006). To show the first characters meanwhile, a draft is streamed apart from the
confirmed text. It is never saved: confirmation discards it with `answer_draft_reset` and
publishes the confirmed body. This is a pure state machine without I/O; it reports only the delta
that may be shown and whether the draft already shown must be discarded.
"""

from __future__ import annotations

from dataclasses import dataclass

from .chat_turn_state import TurnStateUpdateFilter, starts_like_bare_turn_state_update
from .llm_protocol_leak import REASONING_CLOSE_TAG, reasoning_answer_start
from .web_search import (
    resolve_web_search_citations,
    split_web_search_citation_stream_text,
    strip_web_search_citation_html,
)

# 見える文字（前後の空白を除く）がこの数に達するまで下書きを出さない。タグ無しの封筒 JSON かどうかは
# 先頭の数文字では決まらないことがあり、短い前置きだけで終わるステップでは確定の配信で足りる。
# Nothing is drafted until this many visible characters (surrounding whitespace excluded) have
# arrived. A few leading characters may not tell whether the body is an untagged envelope JSON, and
# a step that ends after a short preamble is served well enough by the confirmed delivery.
DRAFT_MIN_VISIBLE_CHARS = 24


@dataclass(frozen=True)
class AnswerDraftUpdate:
    """One feed result: ``reset`` discards the draft already shown, then ``text`` is appended."""

    text: str = ""
    reset: bool = False


class AnswerDraftFilter:
    """Turn the body chunks of one decision step into draft deltas.

    1ステップにつき1つ作る。内部状態の封筒は取り除き、引用マーカーは下書きでは表示しない（確定時に
    チップへ置換される）。コードの外に `</think>` が現れたら、それまでの下書きを捨ててその後ろから
    やり直す。確定時の `strip_leaked_reasoning_chunks` と同じ規則で判定する。
    Create one per step. State envelopes are removed and citation markers are not shown in a draft
    (confirmation replaces them with chips). A `</think>` outside code discards the draft so far and
    restarts after it, by the same rule `strip_leaked_reasoning_chunks` applies at confirmation.
    """

    def __init__(self, latest_user_message: str = "") -> None:
        self._latest_user_message = latest_user_message
        # このステップで受け取った生の本文すべてと、現在の区間（最後の `</think>` の後ろ）の開始位置。
        # All raw body received in this step, and where the current segment (after the last
        # `</think>`) begins.
        self._seen = ""
        self._segment_start = 0
        self._start_segment()

    def _start_segment(self) -> None:
        self._envelope_filter = TurnStateUpdateFilter()
        # 下書きを出し始める前に溜めている、封筒を除いた本文。
        # Body, envelopes removed, waiting until drafting may begin.
        self._held = ""
        self._drafting = False
        # 先頭がタグ無しの封筒 JSON に見えるため、この区間は下書きしない。
        # The segment opens like an untagged envelope JSON, so it is not drafted.
        self._blocked = False
        self._citation_tail = ""
        self._emitted = False

    def feed(self, chunk: str) -> AnswerDraftUpdate:
        """Return the draft delta for ``chunk``, flagging a discard of the draft shown so far."""
        if not chunk:
            return AnswerDraftUpdate()
        previous_length = len(self._seen)
        self._seen += chunk
        restart_at = self._find_reasoning_restart(previous_length)
        if restart_at is None:
            return AnswerDraftUpdate(text=self._advance(chunk))
        reset = self._emitted
        self._segment_start = restart_at
        self._start_segment()
        return AnswerDraftUpdate(text=self._advance(self._seen[restart_at:]), reset=reset)

    # 新しく届いた分に閉じタグが含まれるときだけ全文を調べる。タグはチャンクをまたぎうるので、
    # 前回の末尾も窓に含める。
    # Scan the whole text only when the newly arrived part holds the closing tag; the tag can
    # straddle chunks, so the window includes the previous tail.
    def _find_reasoning_restart(self, previous_length: int) -> int | None:
        window_start = max(previous_length - (len(REASONING_CLOSE_TAG) - 1), 0)
        if REASONING_CLOSE_TAG not in self._seen[window_start:]:
            return None
        answer_start = reasoning_answer_start(self._seen, self._latest_user_message)
        return answer_start if answer_start > self._segment_start else None

    def _advance(self, chunk: str) -> str:
        visible = self._envelope_filter.feed(chunk)
        if self._blocked:
            return ""
        if not self._drafting:
            self._held += visible
            if len(self._held.strip()) < DRAFT_MIN_VISIBLE_CHARS:
                return ""
            visible = self._held.lstrip()
            self._held = ""
            if starts_like_bare_turn_state_update(visible):
                self._blocked = True
                return ""
            self._drafting = True
        text = self._display_text(visible)
        if text:
            self._emitted = True
        return text

    # 引用マーカーが途中で切れていれば次のチャンクまで保留し、完結したものは下書きから除く。
    # A marker cut off mid-way waits for the next chunk; complete ones are removed from the draft.
    def _display_text(self, visible: str) -> str:
        complete, self._citation_tail = split_web_search_citation_stream_text(f"{self._citation_tail}{visible}")
        return resolve_web_search_citations(strip_web_search_citation_html(complete), None).text
