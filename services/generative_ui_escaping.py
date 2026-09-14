# 生成UIのソースが「二重にエスケープされた」状態で届く事故を、決定的に元へ戻す。
# モデルは JSON 文字列の中へコードを書くとき、改行を `\n` ではなく `\\n` と書くことがある。
# JSON としては正しく読めてしまうため検証は通り、ブラウザでは `<div id=\"app\">` や
# `const a = 1;\n` のような壊れたソースが実行されて画面が真っ白になる。プロンプトで
# 言い直しても発生率は下がらないので、受け取り側で検出して1段だけ復号する。
# Deterministically undo a double-escaped generated-UI payload. When a model writes code inside
# a JSON string it sometimes emits `\\n` where `\n` was meant. The JSON still parses, so server
# validation passes, and the browser then runs markup like `<div id=\"app\">` or code like
# `const a = 1;\n` and renders nothing. Re-wording the prompt does not move the rate, so the
# receiving side detects the condition and decodes exactly one level.

from __future__ import annotations

import re

from services.generative_ui_javascript import javascript_structure_error

__all__ = ["repair_over_escaped_sources"]

# 1段だけ復号する対象。`\uXXXX` は別扱いで、それ以外の未知のエスケープは触らない。
# The escapes decoded by one pass; `\uXXXX` is handled separately and unknown escapes are kept.
_SINGLE_CHAR_ESCAPES = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "b": "\b",
    "f": "\f",
    '"': '"',
    "'": "'",
    "\\": "\\",
    "/": "/",
}
_UNICODE_ESCAPE_RE = re.compile(r"[0-9a-fA-F]{4}")
# タグの内側に現れる `\"` / `\'`。正しいHTMLには存在せず、二重エスケープの決定的な証拠。
# An escaped quote inside a tag never appears in correct HTML; it is conclusive evidence.
_ESCAPED_QUOTE_IN_TAG_RE = re.compile(r"<[A-Za-z/!][^<>]*\\[\"']")
# 復号したことで消えるべき痕跡。復号後にまだ残っていれば、判定が誤りだったとみなす。
# Evidence that must disappear after decoding; if it survives, the decision was wrong.
_ESCAPE_SEQUENCE_RE = re.compile(r"\\[nrt\"']")


def _decode_one_level(value: str) -> str:
    """Decode one level of JSON-style escapes, leaving unknown escapes untouched."""
    pieces: list[str] = []
    index = 0
    length = len(value)
    while index < length:
        char = value[index]
        if char != "\\" or index + 1 >= length:
            pieces.append(char)
            index += 1
            continue
        following = value[index + 1]
        decoded = _SINGLE_CHAR_ESCAPES.get(following)
        if decoded is not None:
            pieces.append(decoded)
            index += 2
            continue
        if following == "u" and _UNICODE_ESCAPE_RE.fullmatch(value[index + 2 : index + 6]):
            pieces.append(chr(int(value[index + 2 : index + 6], 16)))
            index += 6
            continue
        pieces.append(char)
        index += 1
    return "".join(pieces)


def _html_is_over_escaped(html: str) -> bool:
    return bool(_ESCAPED_QUOTE_IN_TAG_RE.search(html))


# 二重を超えて三重にエスケープした出力もある。段数を決め打ちせず、壊れている間だけ
# 1段ずつ剥がす。上限を置くのは、直らない入力で回り続けないため。
# Some output is escaped three levels deep, not two. Rather than assuming a depth, one level is
# peeled at a time while the source stays broken; the cap stops an unfixable input from looping.
MAX_DECODE_PASSES = 3


def _decode_until_plausible(js: str) -> tuple[str, int] | None:
    """Peel escape levels off broken JavaScript until it parses; report how many it took."""
    candidate = js
    for passes in range(1, MAX_DECODE_PASSES + 1):
        decoded = _decode_one_level(candidate)
        if decoded == candidate:
            return None
        if javascript_structure_error(decoded) is None:
            return decoded, passes
        candidate = decoded
    return None


def _javascript_is_over_escaped(js: str) -> bool:
    """Whether the JavaScript is broken now and becomes plausible after decoding."""
    if not js.strip() or not _ESCAPE_SEQUENCE_RE.search(js):
        return False
    if javascript_structure_error(js) is None:
        return False
    return _decode_until_plausible(js) is not None


def _decode_levels(value: str, passes: int) -> str:
    """Decode up to ``passes`` levels, stopping once no stray escape is left."""
    for _ in range(passes):
        if not _ESCAPE_SEQUENCE_RE.search(value):
            break
        value = _decode_one_level(value)
    return value


def repair_over_escaped_sources(
    html: str,
    css: str,
    js: str,
) -> tuple[str, str, str, bool]:
    """Return the sources with one or more levels of stray escaping removed.

    過剰エスケープはJSON出力全体に一様に起きるため、どれか1つで確証が取れた時点で
    3つとも復号する。ただし復号がJSを壊す場合は、その場で元へ戻す。
    Over-escaping applies uniformly to the whole JSON emission, so once one field proves it, all
    three are decoded. A decode that would break the JavaScript is reverted on the spot.
    """
    if not (_html_is_over_escaped(html) or _javascript_is_over_escaped(js)):
        return html, css, js, False

    decoded_js, passes = js, 1
    if js.strip():
        plausible = _decode_until_plausible(js) if javascript_structure_error(js) else None
        if plausible is not None:
            decoded_js, passes = plausible
        else:
            candidate = _decode_one_level(js)
            # 復号でJSが壊れるなら、そもそも過剰エスケープではない。マークアップだけを直す。
            # A decode that breaks the JavaScript means it was not over-escaped; fix markup only.
            if javascript_structure_error(candidate) is None:
                decoded_js = candidate
    decoded_html = _decode_levels(html, passes)
    decoded_css = _decode_levels(css, passes)
    changed = (decoded_html, decoded_css, decoded_js) != (html, css, js)
    return decoded_html, decoded_css, decoded_js, changed
