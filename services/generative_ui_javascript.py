# 生成UIのJavaScriptを、ブラウザで実行する前に構造レベルで検査する。
# 構文が壊れたJSはサンドボックス内で最初の1行から失敗し、画面が真っ白になるだけで
# サーバー側の検証は通ってしまう。ここではパーサを追加せず、コメント・文字列・
# 正規表現リテラルを読み飛ばす1パス走査で「括弧の対応」と「明らかに壊れた宣言・代入」
# だけを判定する。安全性トークンの検査は services/generative_ui.py が引き続き担当する。
# Structural checks for generated-UI JavaScript before it ever runs in a browser.
# Broken syntax fails on the first line inside the sandbox and renders a blank frame
# while still passing server-side validation. Rather than adding a parser dependency,
# this module performs a single scan that skips comments, strings, and regular-expression
# literals, then reports unbalanced brackets and obviously broken declarations or
# assignments. Token-level safety validation stays in services/generative_ui.py.

from __future__ import annotations

import re
from collections.abc import Iterable

# 正規表現リテラルの直前に現れうるトークン。これ以外の後ろの `/` は除算として扱う。
# Tokens that may precede a regular-expression literal; any other `/` is division.
_REGEX_PREFIX_CHARS = set("(,=:[!&|?{};+-*%~^<>\n")
_REGEX_PREFIX_KEYWORDS = frozenset(
    {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "do", "else", "case", "yield", "await"}
)
_BRACKET_PAIRS = {")": "(", "]": "[", "}": "{"}
# 名前のない宣言（`const = ;`）と、値のない代入（`const broken = ;`）。
# A declaration with no name (`const = ;`) and an assignment with no value (`const broken = ;`).
_NAMELESS_DECLARATION_RE = re.compile(r"\b(?:const|let|var)\s*(?:=|;)")
_VALUELESS_ASSIGNMENT_RE = re.compile(r"(?<![=!<>])=\s*[;)\]}]")
# コード位置に現れるバックスラッシュ。文字列・正規表現・テンプレートの外では、識別子の
# `\uXXXX` 表記を除いて常に構文エラーであり、二重エスケープされた出力の目印にもなる。
# A backslash in code position. Outside strings, regular expressions, and templates it is always
# a syntax error except for the `\uXXXX` identifier form, and it marks double-escaped output.
_STRAY_BACKSLASH_RE = re.compile(r"\\(?!u[0-9a-fA-F]{4})")
_MAX_REPORTED_CHARS = 160
# 直前トークンの判定に必要な範囲だけを見る。全文を連結すると走査が O(n^2) になる。
# Only the preceding tokens matter; joining the whole buffer would make the scan O(n^2).
_REGEX_LOOKBEHIND_CHARS = 24


def _is_regex_start(code: str, index: int) -> bool:
    """Decide whether the `/` at ``index`` opens a regular-expression literal."""
    cursor = index - 1
    while cursor >= 0 and code[cursor] in " \t":
        cursor -= 1
    if cursor < 0:
        return True
    previous = code[cursor]
    if previous in _REGEX_PREFIX_CHARS:
        return True
    if previous.isalnum() or previous in "_$":
        word_end = cursor + 1
        while cursor >= 0 and (code[cursor].isalnum() or code[cursor] in "_$"):
            cursor -= 1
        return code[cursor + 1 : word_end] in _REGEX_PREFIX_KEYWORDS
    return False


def scan_javascript(source: str) -> tuple[str, str | None, list[int]]:
    """Return the blanked-out code, the first structural error, and the code-position indices.

    Strings, comments, regular expressions, and the literal text of template literals are
    replaced by placeholders so the caller can pattern-match code structure without matching
    text that merely looks like code. `${...}` substitutions are code, not text, and are
    scanned as such: a broken expression there is a syntax error like any other.
    """
    code: list[str] = []
    code_indices: list[int] = []
    stack: list[str] = []
    # モードスタック。テンプレートリテラルの `${` で code へ戻り、対応する `}` で template
    # へ戻る。これを持たないと `${}` の中身が文字列として読み飛ばされ、そこにある構文
    # エラーがサーバー検証をすり抜けて空のiframeになる。
    # Mode stack: a template literal's `${` re-enters code, and its matching `}` returns to the
    # template. Without it, a substitution's contents are skipped as text and a syntax error
    # inside one passes server validation and becomes an empty iframe.
    modes: list[str] = ["code"]
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        following = source[index + 1] if index + 1 < length else ""

        if modes[-1] == "template":
            if char == "\\":
                index += 2
                continue
            if char == "`":
                modes.pop()
                index += 1
                continue
            if char == "$" and following == "{":
                modes.append("code")
                stack.append("${")
                index += 2
                continue
            index += 1
            continue

        if char == "/" and following == "/":
            index += 2
            while index < length and source[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and following == "*":
            index += 2
            while index + 1 < length and not (source[index] == "*" and source[index + 1] == "/"):
                index += 1
            index += 2
            continue
        if char == "`":
            modes.append("template")
            code.append('""')
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            closed = False
            while index < length:
                current = source[index]
                if current == "\\":
                    index += 2
                    continue
                if current == quote:
                    index += 1
                    closed = True
                    break
                # 通常の文字列リテラルは行をまたげない。閉じずに改行へ達したものは必ず
                # 構文エラーで、実行すれば最初の1行で止まり画面が空になる。
                # An ordinary string literal cannot span lines, so one that reaches a newline
                # unclosed is always a syntax error that blanks the frame on the first line.
                if current in "\r\n":
                    break
                index += 1
            if not closed:
                return "".join(code), f"JavaScript syntax error: unterminated {quote} string", code_indices
            code.append('""')
            continue
        if char == "/" and _is_regex_start(tail := "".join(code[-_REGEX_LOOKBEHIND_CHARS:]), len(tail)):
            cursor = index + 1
            closed = False
            in_class = False
            while cursor < length:
                current = source[cursor]
                if current == "\\":
                    cursor += 2
                    continue
                if current in "\r\n":
                    break
                if current == "[":
                    in_class = True
                elif current == "]":
                    in_class = False
                elif current == "/" and not in_class:
                    closed = True
                    break
                cursor += 1
            if closed:
                index = cursor + 1
                while index < length and source[index].isalpha():
                    index += 1
                code.append("/RE/")
                continue

        if char in "([{":
            stack.append(char)
        elif char in _BRACKET_PAIRS:
            if char == "}" and stack and stack[-1] == "${":
                # テンプレート置換の終わり。括弧としては数えず、テンプレート本体へ戻る。
                # End of a template substitution: not a bracket, so return to the template body.
                stack.pop()
                modes.pop()
                index += 1
                continue
            if not stack or stack[-1] != _BRACKET_PAIRS[char]:
                return "".join(code), f"JavaScript syntax error: unmatched `{char}`", code_indices
            stack.pop()
        code.append(char)
        code_indices.append(index)
        index += 1

    if modes[-1] == "template":
        return "".join(code), "JavaScript syntax error: unclosed template literal", code_indices
    if stack:
        unclosed = "${" if stack[-1] == "${" else stack[-1]
        return "".join(code), f"JavaScript syntax error: unclosed `{unclosed}`", code_indices
    return "".join(code), None, code_indices


def strip_javascript_noise(source: str) -> tuple[str, str | None]:
    """Return the code with literals blanked out, plus the first structural error."""
    code, error, _ = scan_javascript(source)
    return code, error


def javascript_structure_error(source: str) -> str | None:
    """Return the first structural JavaScript problem, or ``None`` when plausible."""
    if not isinstance(source, str) or not source.strip():
        return None
    code, bracket_error = strip_javascript_noise(source)
    if bracket_error:
        return bracket_error
    match = _NAMELESS_DECLARATION_RE.search(code)
    if match:
        return f"JavaScript syntax error: a declaration has no name near `{match.group(0)[:_MAX_REPORTED_CHARS]}`"
    match = _VALUELESS_ASSIGNMENT_RE.search(code)
    if match:
        return f"JavaScript syntax error: an assignment has no value near `{match.group(0)[:_MAX_REPORTED_CHARS]}`"
    match = _STRAY_BACKSLASH_RE.search(code)
    if match:
        context = code[match.start() : match.start() + _MAX_REPORTED_CHARS].strip()
        return f"JavaScript syntax error: a stray backslash appears outside a string near `{context}`"
    return None


def unsupported_library_references(js: str, names: Iterable[str]) -> list[str]:
    """Return the dropped library names that the JavaScript still calls into.

    未対応ライブラリの宣言を黙って削除しても、それを参照するコードが残っていれば
    サンドボックスでは必ず失敗する。参照が残っている場合だけ名前を返す。
    Silently removing an unsupported library declaration still leaves code that calls
    it, which always fails in the sandbox. Only names that are still referenced are
    returned.
    """
    code, _ = strip_javascript_noise(js if isinstance(js, str) else "")
    referenced: list[str] = []
    for name in names:
        identifier = re.split(r"[^A-Za-z0-9_$]", str(name).strip())[0]
        if not identifier or identifier in referenced:
            continue
        pattern = re.compile(r"(?<![\w$.])" + re.escape(identifier) + r"\s*[.\[(]", re.IGNORECASE)
        if pattern.search(code):
            referenced.append(identifier)
    return referenced


# モデルはコード中に全角記号やUnicodeのマイナス記号を混ぜることがある。文字列の中なら
# ただの文字だが、コードの位置に現れると JS では必ず不正なトークンになり、最初の1行で
# 止まって画面が空になる。文字列・コメント・テンプレート本文はそのままに、コード位置の
# 文字だけを対応するASCIIへ直す。
# Models sometimes mix fullwidth punctuation or a Unicode minus into the code. Inside a string
# those are ordinary characters, but in code position JavaScript always reads them as an invalid
# token, stops on the first line, and leaves a blank frame. Only code-position characters are
# mapped to their ASCII equivalents; strings, comments, and template text are left untouched.
_CODE_HOMOGLYPHS = {
    "−": "-",  # minus sign
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",  # en dash
    "—": "-",  # em dash
    "―": "-",
    "（": "(",
    "）": ")",
    "［": "[",
    "］": "]",
    "｛": "{",
    "｝": "}",
    "；": ";",
    "，": ",",
    "、": ",",
    "．": ".",
    "。": ".",
    "：": ":",
    "＋": "+",
    "－": "-",
    "＊": "*",
    "／": "/",
    "％": "%",
    "＝": "=",
    "＜": "<",
    "＞": ">",
    "！": "!",
    "？": "?",
    "＆": "&",
    "｜": "|",
    "＾": "^",
    "～": "~",
}


def repair_code_homoglyphs(source: str) -> str:
    """Replace code-position lookalike characters with the ASCII they stand for."""
    if not isinstance(source, str) or not source:
        return source
    if not any(character in source for character in _CODE_HOMOGLYPHS):
        return source
    _, _, code_indices = scan_javascript(source)
    characters = list(source)
    for index in code_indices:
        replacement = _CODE_HOMOGLYPHS.get(characters[index])
        if replacement is not None:
            characters[index] = replacement
    return "".join(characters)
