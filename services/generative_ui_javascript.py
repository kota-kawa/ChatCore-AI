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


def strip_javascript_noise(source: str) -> tuple[str, str | None]:
    """Return the code with literals blanked out, plus the first structural error.

    Strings, template literals, comments, and regular expressions are replaced by
    placeholders so the caller can pattern-match code structure without matching
    text that merely looks like code.
    """
    code: list[str] = []
    stack: list[str] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        following = source[index + 1] if index + 1 < length else ""

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
        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            while index < length:
                current = source[index]
                if current == "\\":
                    index += 2
                    continue
                if current == quote:
                    index += 1
                    break
                if current in "\r\n" and quote != "`":
                    break
                index += 1
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
            if not stack or stack[-1] != _BRACKET_PAIRS[char]:
                return "".join(code), f"JavaScript syntax error: unmatched `{char}`"
            stack.pop()
        code.append(char)
        index += 1

    if stack:
        return "".join(code), f"JavaScript syntax error: unclosed `{stack[-1]}`"
    return "".join(code), None


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
