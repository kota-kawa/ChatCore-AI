"""Detect model-internal tool-call protocol leaking into user-facing text.

GPT-6 Luna と GPT-OSS はツール呼び出しを内部の Harmony 形式で表す。サンプリングが崩れると
`assistant to=functions.web_search` や `<|im_end|>` のような内部形式が本文として流れ、そのまま
出力上限まで繰り返すことがある（issue #771）。その先は回答ではないので、境目で打ち切る。
GPT-6 Luna and GPT-OSS express tool calls in the internal Harmony format. When sampling derails,
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
)
# コードブロックとインラインコード。生成途中で閉じていないものも、その行末（ブロックは本文末）まで
# コードとみなす。
# Code fences and inline code spans; one still open mid-stream counts as code up to the end of its
# line (a fence, to the end of the text).
_CODE_SPAN_PATTERN = re.compile(r"```.*?(?:```|\Z)|`[^`\n]*(?:`|(?=\n)|\Z)", re.DOTALL)
# 境界をまたぐ目印を見落とさないよう、前回までの本文の末尾をこの長さだけ読み直す。
# Re-scan this much of the earlier text so a marker split across chunks is still found.
_RESCAN_CHARS = 64


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
    """Track one stream and report the chunk prefix that precedes leaked protocol."""

    def __init__(self) -> None:
        self._text = ""
        self.tripped = False
        # 目印がすでに通過したチャンクから始まっていた場合に、取り消すべき文字数。
        # Characters already passed on in earlier chunks when the marker began there.
        self.overflow_chars = 0

    def feed(self, chunk: str) -> str:
        """Return the part of ``chunk`` to keep; set ``tripped`` once a leak begins."""
        if self.tripped:
            return ""
        chunk_start = len(self._text)
        self._text += chunk
        leak_at = find_protocol_leak(self._text, chunk_start - _RESCAN_CHARS)
        if leak_at is None:
            return chunk
        self.tripped = True
        self.overflow_chars = max(chunk_start - leak_at, 0)
        return chunk[: max(leak_at - chunk_start, 0)]
