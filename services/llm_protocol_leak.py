"""Detect model-internal tool-call protocol leaking into user-facing text.

GPT-6 Luna と GPT-OSS はツール呼び出しを内部の Harmony 形式で、Qwen は XML 風のタグで表す。サンプリングが崩れると
`assistant to=functions.web_search` や `<|im_end|>` のような内部形式が本文として流れ、そのまま
出力上限まで繰り返すことがある（issue #771）。その先は回答ではないので、境目で打ち切る。
GPT-6 Luna and GPT-OSS express tool calls in the internal Harmony format, Qwen in XML-like tags. When sampling derails,
strings such as `assistant to=functions.web_search` or `<|im_end|>` stream as body text and can
repeat up to the output cap (issue #771). Nothing after that point is an answer, so cut there.
"""

from __future__ import annotations

import re

# 先頭の任意の1語は `liassistant to=functions...` のように区切りが崩れた役割名を同じ位置から落とすため。
# The optional leading word drops a garbled role prefix such as `liassistant to=functions...` with the marker.
_PROTOCOL_LEAK_PATTERN = re.compile(
    r"(?:\S*[ \t]+)?\bto=functions\.[A-Za-z_]"
    r"|\S*\bmulti_tool_use\.parallel\b"
    r"|<\|(?:im_start|im_end|im_sep|start|end|message|channel|call|return|constrain|assistant|user|system|endoftext)\|>"
    r"|</\|?assistant\|?>"
    # Qwen はツール呼び出しを XML 風のタグで表す / Qwen expresses tool calls as XML-like tags.
    r"|</?tool_call>|<function=[A-Za-z_]|</function>|<parameter=[A-Za-z_]|</parameter>"
)
# コードブロックとインラインコード。生成途中で閉じていないものも、その行末（ブロックは本文末）まで
# コードとみなす。
# Code fences and inline code spans; one still open mid-stream counts as code up to the end of its
# line (a fence, to the end of the text).
_CODE_SPAN_PATTERN = re.compile(r"```.*?(?:```|\Z)|`[^`\n]*(?:`|(?=\n)|\Z)", re.DOTALL)
# 境界をまたぐ目印を見落とさないよう、前回までの本文の末尾をこの長さだけ読み直す。
# Re-scan this much of the earlier text so a marker split across chunks is still found.
_RESCAN_CHARS = 64


def _prefixes(literal: str, min_chars: int = 1) -> str:
    return "|".join(re.escape(literal[:end]) for end in range(len(literal), min_chars - 1, -1))


# 本文の末尾が、続きしだいで目印の頭になりうる形。逐次配信では渡した文字を取り消せないため、この部分
# だけは次のチャンクまで保留する（`<|im_`、`liassis`、`liassistant to=fun` など）。ふつうの文章の
# 末尾が当たっても、次のチャンクで目印にならないと分かった時点で渡す。
# 崩れた語の頭（`li` | `assistant to=...` の `li`）のように予測できない分は、渡した後で overflow_chars として
# 報告するだけで、逐次配信では取り消せない。
# A text end that could become the head of a marker once more text arrives. A streamed character
# cannot be taken back, so only this part waits for the next chunk (`<|im_`, `liassis`,
# `liassistant to=fun`). Ordinary prose that happens to match is released with the next chunk.
# A head that cannot be foreseen (the `li` of `li` | `assistant to=...`) is only reported through
# overflow_chars after release; a streamed path cannot take it back.
_PARTIAL_MARKER_AT_END = re.compile(
    r"(?:</?\|?[A-Za-z_]*\|?=?"
    rf"|(?:\S*[ \t]+)?\b(?:{_prefixes('to=functions.')})"
    rf"|\S*\b(?:{_prefixes('multi_tool_use.parallel')})"
    # Harmony の役割名が崩れて前に付いた1語 / a garbled Harmony role word ahead of `to=functions`
    rf"|\S*(?:{_prefixes('assistant', 2)})[ \t]*"
    r")\Z"
)


def find_protocol_leak(text: str, start: int = 0) -> int | None:
    """Return the offset where leaked protocol begins, or ``None``.

    コードの中は、利用者が内部形式そのものを尋ねた回答でありうるため対象外にする。コードの範囲は
    目印が見つかったときだけ求め、通常のチャンクでは本文全体を走査しない。
    Matches inside code are skipped: the user may have asked about the format itself. Code spans
    are computed only once a marker is found, so ordinary chunks never rescan the whole text.
    """
    code_spans: list[tuple[int, int]] | None = None
    for match in _PROTOCOL_LEAK_PATTERN.finditer(text, max(start, 0)):
        if code_spans is None:
            code_spans = [span.span() for span in _CODE_SPAN_PATTERN.finditer(text)]
        if not any(span_start <= match.start() < span_end for span_start, span_end in code_spans):
            return match.start()
    return None


class ProtocolLeakGuard:
    """Track one stream and report the text that precedes leaked protocol.

    目印の頭になりうる末尾は保留し、次のチャンクかストリームの終わりの ``flush`` で渡す。
    A text end that could start a marker is held until the next chunk or ``flush`` at the end.
    """

    def __init__(self) -> None:
        self._text = ""
        self._released = 0
        self.tripped = False
        # 保留で捉えきれない目印（前に付く崩れた語が長いなど）で、すでに渡した分のうち取り消すべき文字数。
        # Characters already released that must be retracted when the hold-back missed a marker
        # head (for example a long garbled leading word).
        self.overflow_chars = 0

    def feed(self, chunk: str) -> str:
        """Return the text now safe to pass on; set ``tripped`` once a leak begins."""
        if self.tripped:
            return ""
        chunk_start = len(self._text)
        self._text += chunk
        leak_at = find_protocol_leak(self._text, chunk_start - _RESCAN_CHARS)
        if leak_at is not None:
            self.tripped = True
            self.overflow_chars = max(self._released - leak_at, 0)
            return self._release(max(leak_at, self._released))
        held = _PARTIAL_MARKER_AT_END.search(self._text, max(len(self._text) - _RESCAN_CHARS, self._released))
        return self._release(held.start() if held else len(self._text))

    def flush(self) -> str:
        """Return the held-back text; nothing once a leak has tripped the guard."""
        if self.tripped:
            return ""
        return self._release(len(self._text))

    def _release(self, end: int) -> str:
        released = self._text[self._released : end]
        self._released = end
        return released
