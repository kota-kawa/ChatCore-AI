from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import escape as escape_html
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


ARTIFACT_BLOCK_RE = re.compile(
    r"```(?:chatcore-artifact|generative-ui|generative_ui|ui_artifact)(?:\s+json)?\s*"
    r"(?P<json>\{[\s\S]*?\})\s*```",
    re.IGNORECASE,
)
ARTIFACT_OPEN_FENCE_RE = re.compile(
    r"```(?:chatcore-artifact|generative-ui|generative_ui|ui_artifact)(?:\s+json)?[^\S\n]*\n?",
    re.IGNORECASE,
)
INTERACTIVE_BUTTONS_BLOCK_RE = re.compile(
    r"```(?:chatcore-buttons|interactive-buttons|interactive_buttons)(?:\s+json)?\s*"
    r"(?P<json>\{[\s\S]*?\})\s*```",
    re.IGNORECASE,
)
GENERIC_JSON_BLOCK_RE = re.compile(
    r"```json\s*(?P<json>\{[\s\S]*?\})\s*```",
    re.IGNORECASE,
)
FENCED_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.IGNORECASE)
SOURCE_CODE_BLOCK_RE = re.compile(
    r"```(?P<lang>html|css|js|javascript)\s*(?P<code>[\s\S]*?)```",
    re.IGNORECASE,
)

MAX_ARTIFACTS_PER_MESSAGE = 3
MAX_ARTIFACT_HTML_CHARS = 12000
MAX_ARTIFACT_CSS_CHARS = 12000
MAX_ARTIFACT_JS_CHARS = 18000
MAX_ARTIFACT_TOTAL_CHARS = 36000
MIN_ARTIFACT_HEIGHT = 160
MAX_ARTIFACT_HEIGHT = 900

_BANNED_HTML_TAG_RE = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|link|meta|base)\b",
    re.IGNORECASE,
)
_SCRIPT_TAG_RE = re.compile(
    r"<\s*script\b[^>]*>(?P<body>[\s\S]*?)<\s*/\s*script\s*>",
    re.IGNORECASE,
)
_STYLE_TAG_RE = re.compile(
    r"<\s*style\b[^>]*>(?P<body>[\s\S]*?)<\s*/\s*style\s*>",
    re.IGNORECASE,
)
_BLOCKED_ELEMENT_RE = re.compile(
    r"<\s*(script|iframe|object|embed)\b[^>]*>[\s\S]*?<\s*/\s*\1\s*>",
    re.IGNORECASE,
)
_BLOCKED_TAG_RE = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|link|meta|base)\b[^>]*>",
    re.IGNORECASE,
)
_EVENT_ATTR_RE = re.compile(
    r"\s(?P<name>on[a-z0-9_-]+)\s*=\s*(?P<value>\"[^\"]*\"|'[^']*'|[^\s>]+)",
    re.IGNORECASE,
)
_STYLE_ATTR_RE = re.compile(
    r"\s(?P<name>style)\s*=\s*(?P<value>\"[^\"]*\"|'[^']*'|[^\s>]+)",
    re.IGNORECASE,
)
_NAV_ATTR_RE = re.compile(
    r"\s(?P<name>src|href|action|formaction|poster|data|xlink:href|srcset)\s*="
    r"\s*(?P<value>\"[^\"]*\"|'[^']*'|[^\s>]+)",
    re.IGNORECASE,
)
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(?P<value>[^'\"\)]+)\1\s*\)", re.IGNORECASE)
_CSS_IMPORT_RE = re.compile(r"@import\b[^;]*(?:;|$)", re.IGNORECASE)
_ARTIFACT_SOURCE_KEY_RE = re.compile(
    r'"(?P<key>html|markup|body|content|css|style|styles|js|javascript|script)"\s*:',
    re.IGNORECASE,
)
_ARTIFACT_CONTEXT_KEY_RE = re.compile(
    r'"(?:artifact|version|title|name|label|height|description|summary|caption)"\s*:',
    re.IGNORECASE,
)
# 「明示的に生成UIを作ろうとした」強いシグナル。本文の長さに関わらずfallbackを許可する。
# Strong signals that the model explicitly attempted an artifact; allow a fallback
# regardless of how long the surrounding prose is.
_STRONG_ARTIFACT_INTENT_RE = re.compile(
    r"(chatcore-artifact|generative ui|生成UI|artifact)",
    re.IGNORECASE,
)
# 可視化を匂わせる弱いシグナル。通常の文章でも偶発的に出現する（例: 「表やグラフで確認」）
# ため、短い宣言文のときだけfallbackのトリガーにする。
# Weak visualization hints that also appear incidentally in ordinary prose (e.g.
# "check the tables and charts"). Only treat them as intent for short announcements.
_WEAK_ARTIFACT_INTENT_RE = re.compile(
    r"(可視化|図解|インフォグラフィック|ダッシュボード|チャート|グラフ|"
    r"タイムライン|フローチャート|比較表|カードビュー)",
    re.IGNORECASE,
)
_DISPLAY_ONLY_INTENT_RE = re.compile(
    r"(表示します|表示しました|作成します|作成しました|用意しました|以下に示します)",
    re.IGNORECASE,
)
# 弱いシグナルや表示宣言から生成UIを補完するのは、本文が短い宣言文のときに限る。
# Only synthesize a fallback from weak/display-only intent when the prose is short.
_SHORT_INTENT_CHAR_LIMIT = 180
# Web検索結果は <details class="web-search-sources …">…</details> として本文へ差し込まれる。
# fallback生成やintent判定では本文だけを見たいので、このブロックを除去する。
# Web search results are injected as <details class="web-search-sources …">…</details>
# blocks. Strip them before inferring intent or building a fallback so the raw markup
# never leaks into a generated UI card.
_WEB_SEARCH_SOURCES_BLOCK_RE = re.compile(
    r"<details\b[^>]*\bclass\s*=\s*(?P<quote>[\"'])[^\"']*web-search-sources[^\"']*(?P=quote)[^>]*>"
    r"(?:(?!</?details\b)[\s\S])*?</details>",
    re.IGNORECASE,
)
_JS_BANNED_TOKEN_RE = re.compile(
    r"(\bfetch\s*\(|\bXMLHttpRequest\s*\(|\bWebSocket\s*\(|\bEventSource\s*\(|"
    r"\bnavigator\s*\.\s*sendBeacon\b|\b(?:Worker|SharedWorker)\s*\(|"
    r"\bnavigator\s*\.\s*serviceWorker\b|\bimportScripts\b|\bimport\s*\(|\beval\s*\(|"
    r"\bFunction\s*\(|\bdocument\s*\.\s*cookie\b|\blocalStorage\b|"
    r"\bsessionStorage\b|\bindexedDB\b|\bcaches\b|"
    r"\bdocument\s*\.\s*(?:write|writeln)\s*\(|"
    r"\bset(?:Timeout|Interval)\s*\(\s*['\"]|"
    r"\b(?:window|globalThis|self)\s*\.\s*(?:parent|top|opener)\b|"
    r"(?<![\w$])(?:parent|top|opener)\s*\.|"
    r"\bpostMessage\s*\(|"
    r"\b(?:window|document)\s*\.\s*location\b|"
    r"(?<![\w$])location\s*(?:=|\.|\[))",
    re.IGNORECASE,
)
# 日本語: GenerativeUiValidationError として扱う例外情報を表します。
# English: Represent exception details handled as GenerativeUiValidationError.
class GenerativeUiValidationError(ValueError):
    pass


# 日本語: ArtifactCandidate に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ArtifactCandidate.
@dataclass(frozen=True)
class _ArtifactCandidate:
    raw_json: str
    span: tuple[int, int]


# 日本語: InteractiveButtonsV1 に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to InteractiveButtonsV1.
class InteractiveButtonsV1(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    type: Literal["yes_no", "multiple_choice"]
    question: str = Field(min_length=1, max_length=500)
    options: list[str] | None = Field(default=None, max_length=10)

    # 日本語: validate options の検証処理を担当します。
    # English: Handle validating for validate options.
    @model_validator(mode="after")
    def _validate_options(self) -> "InteractiveButtonsV1":
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self.type == "multiple_choice" and not self.options:
            raise ValueError("options is required for multiple_choice")
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self.options:
            self.options = [opt for opt in self.options if opt.strip()]
        return self


# 日本語: GenerativeUiArtifactV1 に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to GenerativeUiArtifactV1.
class GenerativeUiArtifactV1(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    version: Literal[1] = 1
    title: str = Field(default="生成UI", min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    height: int | None = Field(default=None, ge=MIN_ARTIFACT_HEIGHT, le=MAX_ARTIFACT_HEIGHT)
    html: str = Field(default="", max_length=MAX_ARTIFACT_HTML_CHARS)
    css: str = Field(default="", max_length=MAX_ARTIFACT_CSS_CHARS)
    js: str = Field(default="", max_length=MAX_ARTIFACT_JS_CHARS)

    # 日本語: validate html の検証処理を担当します。
    # English: Handle validating for validate html.
    @field_validator("html")
    @classmethod
    def _validate_html(cls, value: str) -> str:
        sanitized = _sanitize_html(value)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if _BANNED_HTML_TAG_RE.search(sanitized):
            raise ValueError("HTML contains a forbidden tag.")
        return sanitized

    # 日本語: validate css の検証処理を担当します。
    # English: Handle validating for validate css.
    @field_validator("css")
    @classmethod
    def _validate_css(cls, value: str) -> str:
        return _sanitize_css(value)

    # 日本語: validate js の検証処理を担当します。
    # English: Handle validating for validate js.
    @field_validator("js")
    @classmethod
    def _validate_js(cls, value: str) -> str:
        sanitized = _sanitize_script_end(value)
        _validate_javascript_safety(sanitized)
        return sanitized

    # 日本語: validate total size の検証処理を担当します。
    # English: Handle validating for validate total size.
    @model_validator(mode="after")
    def _validate_total_size(self) -> "GenerativeUiArtifactV1":
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if len(self.html) + len(self.css) + len(self.js) > MAX_ARTIFACT_TOTAL_CHARS:
            raise ValueError("Sandbox artifact is too large.")
        return self


# 日本語: NormalizedGenerativeResponse に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to NormalizedGenerativeResponse.
@dataclass(frozen=True)
class NormalizedGenerativeResponse:
    text: str
    parts: list[dict[str, Any]] | None
    validation_errors: list[str]


# 日本語: coerce string に関する処理の入口です。
# English: Entry point for logic related to coerce string.
def _coerce_string(value: Any) -> str:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


# 日本語: coerce height に関する処理の入口です。
# English: Entry point for logic related to coerce height.
def _coerce_height(value: Any) -> int | None:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if value is None or value == "":
        return None
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if not match:
            return None
        value = int(match.group(0))
    if isinstance(value, (int, float)):
        return min(max(int(value), MIN_ARTIFACT_HEIGHT), MAX_ARTIFACT_HEIGHT)
    return None


# 日本語: trim artifact sources に関する処理の入口です。
# English: Entry point for logic related to trim artifact sources.
def _trim_artifact_sources(html: str, css: str, js: str) -> tuple[str, str, str]:
    html = html[:MAX_ARTIFACT_HTML_CHARS]
    css = css[:MAX_ARTIFACT_CSS_CHARS]
    js = js[:MAX_ARTIFACT_JS_CHARS]
    overflow = len(html) + len(css) + len(js) - MAX_ARTIFACT_TOTAL_CHARS
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if overflow <= 0:
        return html, css, js

    js_trim = min(len(js), overflow)
    js = js[: len(js) - js_trim]
    overflow -= js_trim
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if overflow <= 0:
        return html, css, js

    css_trim = min(len(css), overflow)
    css = css[: len(css) - css_trim]
    overflow -= css_trim
    if overflow <= 0:
        return html, css, js

    html = html[: max(0, len(html) - overflow)]
    return html, css, js


# 日本語: ensure artifact has body の保証処理を担当します。
# English: Handle ensuring for ensure artifact has body.
def _ensure_artifact_has_body(html: str, js: str) -> str:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if html.strip():
        return html
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if "getElementById('app')" in js or 'getElementById("app")' in js:
        return '<div id="app"></div>'
    return '<div id="app" class="chatcore-generated-root"></div>'


# 日本語: strip json comments に関する処理の入口です。
# English: Entry point for logic related to strip json comments.
def _strip_json_comments(source: str) -> str:
    output: list[str] = []
    in_string = False
    quote = ""
    escaped = False
    index = 0
    # 日本語: 条件が満たされている間、同じ処理を継続します。
    # English: Continue the same work while the condition remains true.
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                in_string = False
            index += 1
            continue
        if char in ("'", '"'):
            in_string = True
            quote = char
            output.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            index += 2
            while index < len(source) and source[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            index += 2
            while index + 1 < len(source) and not (source[index] == "*" and source[index + 1] == "/"):
                index += 1
            index += 2
            continue
        output.append(char)
        index += 1
    return "".join(output)


# 日本語: remove trailing json commas の削除処理を担当します。
# English: Handle removing for remove trailing json commas.
def _remove_trailing_json_commas(source: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", source)


# 日本語: remove json line continuations の削除処理を担当します。
# English: Handle removing for remove json line continuations.
def _remove_json_line_continuations(source: str) -> str:
    return re.sub(r"\\[ \t]*(?:\r\n|\r|\n)[ \t]*", "", source)


# 日本語: escape json string newlines に関する処理の入口です。
# English: Entry point for logic related to escape json string newlines.
def _escape_json_string_newlines(source: str) -> str:
    output: list[str] = []
    in_string = False
    escaped = False
    index = 0
    # 日本語: 条件が満たされている間、同じ処理を継続します。
    # English: Continue the same work while the condition remains true.
    while index < len(source):
        char = source[index]
        if in_string:
            if escaped:
                output.append(char)
                escaped = False
            elif char == "\\":
                output.append(char)
                escaped = True
            elif char == '"':
                output.append(char)
                in_string = False
            elif char == "\r":
                output.append("\\n")
                if index + 1 < len(source) and source[index + 1] == "\n":
                    index += 1
            elif char == "\n":
                output.append("\\n")
            else:
                output.append(char)
            index += 1
            continue

        output.append(char)
        if char == '"':
            in_string = True
            escaped = False
        index += 1
    return "".join(output)


# 日本語: normalize jsonish source の正規化処理を担当します。
# English: Handle normalizing for normalize jsonish source.
def _normalize_jsonish_source(source: str) -> str:
    return _remove_trailing_json_commas(
        _strip_json_comments(
            _escape_json_string_newlines(
                _remove_json_line_continuations(source)
            )
        )
    )


# 日本語: loads artifact json に関する処理の入口です。
# English: Entry point for logic related to loads artifact json.
def _loads_artifact_json(raw_json: str) -> Any:
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        return json.loads(raw_json)
    except json.JSONDecodeError:
        return json.loads(_normalize_jsonish_source(raw_json))


# 日本語: spans overlap に関する処理の入口です。
# English: Entry point for logic related to spans overlap.
def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


# 日本語: span overlaps any に関する処理の入口です。
# English: Entry point for logic related to span overlaps any.
def _span_overlaps_any(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(_spans_overlap(span, existing) for existing in spans)


# 日本語: looks like artifact json に関する処理の入口です。
# English: Entry point for logic related to looks like artifact json.
def _looks_like_artifact_json(source: str) -> bool:
    source_keys = {match.group("key").lower() for match in _ARTIFACT_SOURCE_KEY_RE.finditer(source)}
    return bool(source_keys) and (len(source_keys) >= 2 or bool(_ARTIFACT_CONTEXT_KEY_RE.search(source)))


# 日本語: strip web search sources html に関する処理の入口です。
# English: Entry point for logic related to strip web search sources html.
def _strip_web_search_sources_html(text: str) -> str:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if "web-search-sources" not in text:
        return text
    # ネストした details を含まない最も内側のブロックから順に除去し、変化が無くなるまで
    # 繰り返すことで外側のトレースブロックも安全に取り除く。
    # Remove the innermost blocks first and repeat until stable so nested trace
    # blocks are stripped safely as well.
    current = text
    # 日本語: 条件が満たされている間、同じ処理を継続します。
    # English: Continue the same work while the condition remains true.
    while True:
        stripped = _WEB_SEARCH_SOURCES_BLOCK_RE.sub("", current)
        if stripped == current:
            return current
        current = stripped


# 日本語: infer artifact title に関する処理の入口です。
# English: Entry point for logic related to infer artifact title.
def _infer_artifact_title(text: str) -> str:
    cleaned = FENCED_BLOCK_RE.sub("", _strip_web_search_sources_html(text)).strip()
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for line in cleaned.splitlines():
        line = line.strip(" #:-\t")
        if line:
            return line[:60]
    return "生成UI"


# 日本語: has artifact intent に関する処理の入口です。
# English: Entry point for logic related to has artifact intent.
def _has_artifact_intent(text: str) -> bool:
    stripped = FENCED_BLOCK_RE.sub("", _strip_web_search_sources_html(text)).strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if _STRONG_ARTIFACT_INTENT_RE.search(stripped):
        return True
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if len(stripped) > _SHORT_INTENT_CHAR_LIMIT:
        return False
    return bool(
        _WEAK_ARTIFACT_INTENT_RE.search(stripped)
        or _DISPLAY_ONLY_INTENT_RE.search(stripped)
    )


# 日本語: find balanced object end に関する処理の入口です。
# English: Entry point for logic related to find balanced object end.
def _find_balanced_object_end(source: str, start: int) -> int | None:
    depth = 0
    in_string = False
    quote = ""
    escaped = False
    index = start
    # 日本語: 条件が満たされている間、同じ処理を継続します。
    # English: Continue the same work while the condition remains true.
    while index < len(source):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                in_string = False
            index += 1
            continue

        if char in {"'", '"'}:
            in_string = True
            quote = char
            index += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


# 日本語: find raw artifact candidates に関する処理の入口です。
# English: Entry point for logic related to find raw artifact candidates.
def _find_raw_artifact_candidates(
    text: str,
    excluded_spans: list[tuple[int, int]],
) -> list[_ArtifactCandidate]:
    candidates: list[_ArtifactCandidate] = []
    index = 0
    # 日本語: 条件が満たされている間、同じ処理を継続します。
    # English: Continue the same work while the condition remains true.
    while index < len(text):
        start = text.find("{", index)
        if start == -1:
            break
        if _span_overlaps_any((start, start + 1), excluded_spans):
            index = start + 1
            continue
        end = _find_balanced_object_end(text, start)
        if end is None:
            break
        span = (start, end)
        if not _span_overlaps_any(span, excluded_spans):
            raw_json = text[start:end]
            if _looks_like_artifact_json(raw_json):
                candidates.append(_ArtifactCandidate(raw_json=raw_json, span=span))
        index = end
    return candidates


# 日本語: extract source code artifact candidates に関する処理の入口です。
# English: Entry point for logic related to extract source code artifact candidates.
def _extract_source_code_artifact_candidates(
    text: str,
    occupied_spans: list[tuple[int, int]],
) -> list[_ArtifactCandidate]:
    blocks: list[tuple[str, str, tuple[int, int]]] = []
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for match in SOURCE_CODE_BLOCK_RE.finditer(text):
        span = match.span()
        if _span_overlaps_any(span, occupied_spans):
            continue
        blocks.append((match.group("lang").lower(), match.group("code").strip(), span))

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not blocks:
        return []

    html_parts: list[str] = []
    css_parts: list[str] = []
    js_parts: list[str] = []
    spans: list[tuple[int, int]] = []
    for lang, code, span in blocks:
        if not code:
            continue
        spans.append(span)
        if lang == "html":
            html_parts.append(code)
        elif lang == "css":
            css_parts.append(code)
        else:
            js_parts.append(code)

    if not (html_parts or js_parts):
        return []

    payload = {
        "version": 1,
        "title": _infer_artifact_title(text),
        "description": "HTML/CSS/JavaScriptコードブロックから生成したUIです。",
        "height": 420,
        "html": "\n".join(html_parts),
        "css": "\n".join(css_parts),
        "js": "\n".join(js_parts),
    }
    span = (min(start for start, _ in spans), max(end for _, end in spans))
    return [_ArtifactCandidate(raw_json=json.dumps(payload, ensure_ascii=False), span=span)]


# 日本語: drop trailing json token に関する処理の入口です。
# English: Entry point for logic related to drop trailing json token.
def _drop_trailing_json_token(source: str) -> str:
    # 末尾の不完全なトークン（文字列・数値・リテラル）を1つ取り除く。
    # Drop one trailing JSON token (string / number / literal) so a truncated
    # remainder can be closed into a valid object.
    match = re.search(
        r'(?:"(?:[^"\\]|\\.)*"|[-+0-9.eE]+|true|false|null)\s*$',
        source,
    )
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if match:
        return source[: match.start()].rstrip()
    return source[:-1].rstrip()


# 日本語: repair truncated json に関する処理の入口です。
# English: Entry point for logic related to repair truncated json.
def _repair_truncated_json(source: str) -> str | None:
    # 出力が途中で打ち切られたJSONオブジェクトを最大限復元する。開いた文字列・括弧を
    # 閉じ、末尾の不完全なトークンや区切り文字を削ってから検証する。
    # Best-effort completion of a JSON object whose output was cut off mid-stream.
    start = source.find("{")
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if start == -1:
        return None

    stack: list[str] = []
    in_string = False
    escaped = False
    quote = ""
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for char in source[start:]:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                in_string = False
            continue
        if char in {"'", '"'}:
            in_string = True
            quote = char
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in {"}", "]"}:
            if stack:
                stack.pop()

    if not stack and not in_string:
        # Already balanced; the caller's balanced-object path handles this.
        return None

    candidate = source[start:]
    if in_string:
        if escaped:
            candidate = candidate[:-1]
        candidate += quote

    closers = "".join(reversed(stack))
    # 復元は通常1〜2回で成立する。病的な入力での O(n^2) を避けるため試行回数を制限する。
    # Repair usually succeeds in 1-2 passes; cap attempts to bound worst-case cost.
    for _ in range(64):
        trimmed = candidate.rstrip()
        if not trimmed:
            return None
        last = trimmed[-1]
        if last == ",":
            candidate = trimmed[:-1]
            continue
        if last == ":":
            without_colon = trimmed[:-1].rstrip()
            without_key = re.sub(r'"(?:[^"\\]|\\.)*"\s*$', "", without_colon)
            if without_key == without_colon:
                return None
            candidate = without_key
            continue
        closed = trimmed + closers
        try:
            json.loads(_normalize_jsonish_source(closed))
        except json.JSONDecodeError:
            shortened = _drop_trailing_json_token(trimmed)
            if shortened == trimmed:
                return None
            candidate = shortened
            continue
        return closed
    return None


# 日本語: extract truncated artifact candidates に関する処理の入口です。
# English: Entry point for logic related to extract truncated artifact candidates.
def _extract_truncated_artifact_candidates(
    text: str,
    occupied_spans: list[tuple[int, int]],
) -> list[_ArtifactCandidate]:
    # 閉じフェンスが無いartifactブロック（出力打ち切りや ``` 抜け）を検出する。
    # 復元できれば部分的なUIを描画し、できなくてもspanを記録して壊れたJSONが
    # fallback UIにそのまま流れ込むのを防ぐ。
    # Detect artifact fences that were never closed (truncated output or a missing
    # ```). Recover a partial UI when possible; otherwise still record the span so
    # the broken JSON is stripped from the visible text instead of being dumped.
    candidates: list[_ArtifactCandidate] = []
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for match in ARTIFACT_OPEN_FENCE_RE.finditer(text):
        fence_start = match.start()
        content_start = match.end()
        if _span_overlaps_any((fence_start, content_start), occupied_spans):
            continue
        if text.find("```", content_start) != -1:
            # A closing fence exists; the standard extractors handle this block.
            continue
        brace_start = text.find("{", content_start)
        if brace_start == -1:
            continue
        balanced_end = _find_balanced_object_end(text, brace_start)
        if balanced_end is not None:
            raw_json = text[brace_start:balanced_end]
            span = (fence_start, balanced_end)
        else:
            repaired = _repair_truncated_json(text[brace_start:])
            raw_json = repaired if repaired is not None else ""
            span = (fence_start, len(text))
        candidates.append(_ArtifactCandidate(raw_json=raw_json, span=span))
    return candidates


# 日本語: extract artifact candidates に関する処理の入口です。
# English: Entry point for logic related to extract artifact candidates.
def _extract_artifact_candidates(
    text: str,
    *,
    recover_truncated: bool = False,
) -> list[_ArtifactCandidate]:
    candidates: list[_ArtifactCandidate] = []
    occupied_spans: list[tuple[int, int]] = []

    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for match in ARTIFACT_BLOCK_RE.finditer(text):
        candidate = _ArtifactCandidate(raw_json=match.group("json"), span=match.span())
        candidates.append(candidate)
        occupied_spans.append(candidate.span)

    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for match in GENERIC_JSON_BLOCK_RE.finditer(text):
        span = match.span()
        if _span_overlaps_any(span, occupied_spans):
            continue
        raw_json = match.group("json")
        if not _looks_like_artifact_json(raw_json):
            continue
        candidate = _ArtifactCandidate(raw_json=raw_json, span=span)
        candidates.append(candidate)
        occupied_spans.append(candidate.span)

    source_candidates = _extract_source_code_artifact_candidates(text, occupied_spans)
    candidates.extend(source_candidates)
    occupied_spans.extend(candidate.span for candidate in source_candidates)

    if recover_truncated:
        truncated_candidates = _extract_truncated_artifact_candidates(text, occupied_spans)
        candidates.extend(truncated_candidates)
        occupied_spans.extend(candidate.span for candidate in truncated_candidates)

    fenced_spans = [match.span() for match in FENCED_BLOCK_RE.finditer(text)]
    candidates.extend(_find_raw_artifact_candidates(text, [*fenced_spans, *occupied_spans]))
    return sorted(candidates, key=lambda candidate: candidate.span)


# 日本語: remove candidate spans の削除処理を担当します。
# English: Handle removing for remove candidate spans.
def _remove_candidate_spans(text: str, candidates: list[_ArtifactCandidate]) -> str:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not candidates:
        return text.strip()
    pieces: list[str] = []
    cursor = 0
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for candidate in sorted(candidates, key=lambda item: item.span):
        start, end = candidate.span
        if start < cursor:
            continue
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces).strip()


# 日本語: first present に関する処理の入口です。
# English: Entry point for logic related to first present.
def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for key in keys:
        if key in payload:
            return payload[key]
    return None


# 日本語: strip attribute quotes に関する処理の入口です。
# English: Entry point for logic related to strip attribute quotes.
def _strip_attribute_quotes(raw_value: str) -> str:
    value = raw_value.strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        return value[1:-1]
    return value


# 日本語: sanitize script end に関する処理の入口です。
# English: Entry point for logic related to sanitize script end.
def _sanitize_script_end(value: str) -> str:
    return re.sub(r"</\s*script", r"<\\/script", value, flags=re.IGNORECASE)


# 日本語: strip javascript literals and comments に関する処理の入口です。
# English: Entry point for logic related to strip javascript literals and comments.
def _strip_javascript_literals_and_comments(value: str) -> str:
    output: list[str] = []
    index = 0
    # 日本語: 条件が満たされている間、同じ処理を継続します。
    # English: Continue the same work while the condition remains true.
    while index < len(value):
        char = value[index]
        next_char = value[index + 1] if index + 1 < len(value) else ""

        if char == "/" and next_char == "/":
            index += 2
            while index < len(value) and value[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            index += 2
            while index + 1 < len(value) and not (value[index] == "*" and value[index + 1] == "/"):
                index += 1
            index += 2
            continue
        if char in {"'", '"'}:
            quote = char
            output.append(quote)
            index += 1
            escaped = False
            while index < len(value):
                current = value[index]
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == quote:
                    output.append(quote)
                    index += 1
                    break
                elif current in "\r\n":
                    output.append(current)
                    index += 1
                    break
                index += 1
            continue
        if char == "`":
            output.append("`")
            index += 1
            while index < len(value):
                current = value[index]
                next_current = value[index + 1] if index + 1 < len(value) else ""
                if current == "\\":
                    index += 2
                    continue
                if current == "`":
                    output.append("`")
                    index += 1
                    break
                if current == "$" and next_current == "{":
                    end = _find_balanced_object_end(value, index + 1)
                    if end is not None:
                        output.append(value[index:end])
                        index = end
                        continue
                if current in "\r\n":
                    output.append(current)
                index += 1
            continue

        output.append(char)
        index += 1
    return "".join(output)


# 日本語: validate javascript safety の検証処理を担当します。
# English: Handle validating for validate javascript safety.
def _validate_javascript_safety(value: str) -> None:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if _JS_BANNED_TOKEN_RE.search(_strip_javascript_literals_and_comments(value)):
        raise ValueError("JavaScript uses an API that is not allowed in sandbox artifacts.")


# 日本語: is safe javascript fragment に関する処理の入口です。
# English: Entry point for logic related to is safe javascript fragment.
def _is_safe_javascript_fragment(value: str) -> bool:
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        _validate_javascript_safety(value)
    except ValueError:
        return False
    return True


# 日本語: is safe resource url に関する処理の入口です。
# English: Entry point for logic related to is safe resource url.
def _is_safe_resource_url(value: str) -> bool:
    url = value.strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not url:
        return True
    return (
        url.startswith("data:")
        or url.startswith("blob:")
        or url.startswith("#")
    )


# 日本語: sanitize css に関する処理の入口です。
# English: Entry point for logic related to sanitize css.
def _sanitize_css(value: str) -> str:
    sanitized = _coerce_string(value)
    sanitized = re.sub(r"</\s*style", r"<\\/style", sanitized, flags=re.IGNORECASE)
    sanitized = _CSS_IMPORT_RE.sub("", sanitized)

    # 日本語: replace url に関する処理の入口です。
    # English: Entry point for logic related to replace url.
    def replace_url(match: re.Match[str]) -> str:
        url = match.group("value").strip()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if url.startswith("data:") or url.startswith("blob:") or url.startswith("#"):
            return match.group(0)
        return "url(\"data:,\")"

    return _CSS_URL_RE.sub(replace_url, sanitized)


# 日本語: sanitize html に関する処理の入口です。
# English: Entry point for logic related to sanitize html.
def _sanitize_html(value: str) -> str:
    sanitized = _coerce_string(value)
    sanitized = _BLOCKED_ELEMENT_RE.sub("", sanitized)
    sanitized = _BLOCKED_TAG_RE.sub("", sanitized)

    # 日本語: replace event attr に関する処理の入口です。
    # English: Entry point for logic related to replace event attr.
    def replace_event_attr(match: re.Match[str]) -> str:
        handler = _strip_attribute_quotes(match.group("value"))
        return match.group(0) if _is_safe_javascript_fragment(handler) else ""

    # 日本語: replace style attr に関する処理の入口です。
    # English: Entry point for logic related to replace style attr.
    def replace_style_attr(match: re.Match[str]) -> str:
        style = _strip_attribute_quotes(match.group("value"))
        return match.group(0) if _sanitize_css(style) == style else ""

    # 日本語: replace nav attr に関する処理の入口です。
    # English: Entry point for logic related to replace nav attr.
    def replace_nav_attr(match: re.Match[str]) -> str:
        name = match.group("name")
        value = _strip_attribute_quotes(match.group("value"))
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if _is_safe_resource_url(value):
            return match.group(0)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if name.lower() in {"href", "xlink:href"}:
            return f' {name}="#"'
        return ""

    sanitized = _EVENT_ATTR_RE.sub(replace_event_attr, sanitized)
    sanitized = _STYLE_ATTR_RE.sub(replace_style_attr, sanitized)
    sanitized = _NAV_ATTR_RE.sub(replace_nav_attr, sanitized)
    return sanitized


# 日本語: prepare artifact payload に関する処理の入口です。
# English: Entry point for logic related to prepare artifact payload.
def _prepare_artifact_payload(payload: Any) -> Any:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if isinstance(payload, list):
        payload = next((item for item in payload if isinstance(item, dict)), payload)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not isinstance(payload, dict):
        return payload
    if isinstance(payload.get("artifact"), dict) and not any(
        key in payload for key in ("html", "markup", "body", "content")
    ):
        payload = payload["artifact"]

    html = _coerce_string(_first_present(payload, "html", "markup", "body", "content"))
    css = _coerce_string(_first_present(payload, "css", "style", "styles"))
    js = _coerce_string(_first_present(payload, "js", "javascript", "script"))

    embedded_css: list[str] = []
    embedded_js: list[str] = []

    # 日本語: extract style に関する処理の入口です。
    # English: Entry point for logic related to extract style.
    def extract_style(match: re.Match[str]) -> str:
        embedded_css.append(match.group("body"))
        return ""

    # 日本語: extract script に関する処理の入口です。
    # English: Entry point for logic related to extract script.
    def extract_script(match: re.Match[str]) -> str:
        embedded_js.append(match.group("body"))
        return ""

    html = _STYLE_TAG_RE.sub(extract_style, html)
    html = _SCRIPT_TAG_RE.sub(extract_script, html)
    if embedded_css:
        css = "\n".join(part for part in [css, *embedded_css] if part)
    if embedded_js:
        js = "\n".join(part for part in [js, *embedded_js] if part)
    html = _ensure_artifact_has_body(html, js)
    html, css, js = _trim_artifact_sources(html, css, js)

    title = _coerce_string(_first_present(payload, "title", "name", "label")).strip() or "生成UI"
    description = _coerce_string(_first_present(payload, "description", "summary", "caption")).strip()
    prepared = {
        "version": 1,
        "title": title[:120],
        "description": description[:500] if description else None,
        "height": _coerce_height(payload.get("height")),
        "html": html,
        "css": css,
        "js": js,
    }
    if prepared["description"] is None:
        prepared.pop("description")
    return prepared


# 日本語: validate artifact payload の検証処理を担当します。
# English: Handle validating for validate artifact payload.
def validate_artifact_payload(payload: Any) -> dict[str, Any]:
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        artifact = GenerativeUiArtifactV1.model_validate(_prepare_artifact_payload(payload))
    except ValidationError as exc:
        raise GenerativeUiValidationError(str(exc)) from exc
    except ValueError as exc:
        raise GenerativeUiValidationError(str(exc)) from exc
    return artifact.model_dump(exclude_none=True)


# 日本語: validate interactive buttons payload の検証処理を担当します。
# English: Handle validating for validate interactive buttons payload.
def validate_interactive_buttons_payload(payload: Any) -> dict[str, Any]:
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        buttons = InteractiveButtonsV1.model_validate(payload)
    except ValidationError as exc:
        raise GenerativeUiValidationError(str(exc)) from exc
    except ValueError as exc:
        raise GenerativeUiValidationError(str(exc)) from exc
    return buttons.model_dump(exclude_none=True)


# 日本語: decode message parts に関する処理の入口です。
# English: Entry point for logic related to decode message parts.
def _decode_message_parts(raw_parts: Any) -> list[dict[str, Any]] | None:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not raw_parts:
        return None
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if isinstance(raw_parts, str):
        try:
            raw_parts = json.loads(raw_parts)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            return None
    if not isinstance(raw_parts, list):
        return None

    parts: list[dict[str, Any]] = []
    for part in raw_parts:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "text" and isinstance(part.get("text"), str):
            parts.append({"type": "text", "text": part["text"]})
            continue
        if part_type == "sandbox_artifact":
            try:
                artifact = validate_artifact_payload(part.get("artifact"))
            except GenerativeUiValidationError:
                continue
            parts.append({"type": "sandbox_artifact", "artifact": artifact})
            continue
        if part_type == "interactive_buttons":
            try:
                buttons = validate_interactive_buttons_payload(part.get("buttons"))
            except GenerativeUiValidationError:
                continue
            parts.append({"type": "interactive_buttons", "buttons": buttons})
            continue
    return parts or None


# 日本語: decode message parts に関する処理の入口です。
# English: Entry point for logic related to decode message parts.
def decode_message_parts(raw_parts: Any) -> list[dict[str, Any]] | None:
    return _decode_message_parts(raw_parts)


# 日本語: encode message parts に関する処理の入口です。
# English: Entry point for logic related to encode message parts.
def encode_message_parts(parts: list[dict[str, Any]] | None) -> str | None:
    normalized = _decode_message_parts(parts)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not normalized:
        return None
    return json.dumps(normalized, ensure_ascii=False)


# 日本語: build fallback artifact の組み立て処理を担当します。
# English: Handle building for build fallback artifact.
def _build_fallback_artifact(visible_text: str, raw_text: str) -> dict[str, Any]:
    title = _infer_artifact_title(visible_text or raw_text)
    # Web検索のトレースブロックHTMLがエスケープされてカード本文に流れ込むのを防ぐ。
    # Keep the web-search trace markup out of the escaped card body.
    source_text = _strip_web_search_sources_html(
        visible_text or raw_text or "生成UIを表示するための内容を補完しました。"
    ).strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not source_text:
        source_text = "生成UIを表示するための内容を補完しました。"
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if len(source_text) > 900:
        source_text = f"{source_text[:900].rstrip()}..."
    paragraphs = [
        f"<p>{escape_html(line.strip())}</p>"
        for line in source_text.splitlines()
        if line.strip()
    ]
    if not paragraphs:
        paragraphs = ["<p>生成UIを表示するための内容を補完しました。</p>"]
    payload = {
        "version": 1,
        "title": title,
        "description": "モデル出力から安全なfallback UIを生成しました。",
        "height": 280,
        "html": (
            '<section class="fallback-ui">'
            '<div class="fallback-ui__badge">Generated UI</div>'
            '<div class="fallback-ui__content">'
            f"{''.join(paragraphs)}"
            "</div>"
            "</section>"
        ),
        "css": (
            ".fallback-ui{min-height:220px;padding:20px;border:1px solid #d1d5db;"
            "border-radius:8px;background:linear-gradient(135deg,#f8fafc,#eef2ff);color:#111827;"
            "display:flex;flex-direction:column;gap:14px;justify-content:center;}"
            ".fallback-ui__badge{width:max-content;padding:4px 10px;border-radius:999px;"
            "background:#111827;color:#fff;font-size:12px;font-weight:700;letter-spacing:.04em;}"
            ".fallback-ui__content{display:grid;gap:8px;font-size:15px;line-height:1.65;}"
            ".fallback-ui__content p{margin:0;}"
        ),
        "js": "",
    }
    return validate_artifact_payload(payload)


# 日本語: normalize response with artifacts の正規化処理を担当します。
# English: Handle normalizing for normalize response with artifacts.
def normalize_response_with_artifacts(
    raw_text: str,
    *,
    recover_truncated: bool = False,
    allow_fallback: bool = True,
) -> NormalizedGenerativeResponse:
    text = raw_text if isinstance(raw_text, str) else str(raw_text or "")
    candidates = _extract_artifact_candidates(text, recover_truncated=recover_truncated)
    
    button_candidates: list[_ArtifactCandidate] = []
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for match in INTERACTIVE_BUTTONS_BLOCK_RE.finditer(text):
        button_candidates.append(_ArtifactCandidate(raw_json=match.group("json"), span=match.span()))
        
    has_intent = _has_artifact_intent(text)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not candidates and not button_candidates and not has_intent:
        return NormalizedGenerativeResponse(text=text, parts=None, validation_errors=[])

    artifacts: list[dict[str, Any]] = []
    buttons_list: list[dict[str, Any]] = []
    validation_errors: list[str] = []
    for candidate in candidates[:MAX_ARTIFACTS_PER_MESSAGE]:
        try:
            payload = _loads_artifact_json(candidate.raw_json)
            artifacts.append(validate_artifact_payload(payload))
        except (json.JSONDecodeError, GenerativeUiValidationError) as exc:
            validation_errors.append(str(exc))

    for candidate in button_candidates[:MAX_ARTIFACTS_PER_MESSAGE]:
        try:
            payload = _loads_artifact_json(candidate.raw_json)
            buttons_list.append(validate_interactive_buttons_payload(payload))
        except (json.JSONDecodeError, GenerativeUiValidationError) as exc:
            validation_errors.append(str(exc))

    all_candidates = sorted(candidates + button_candidates, key=lambda c: c.span)
    visible_text = _remove_candidate_spans(text, all_candidates)

    if not artifacts and not buttons_list:
        if not allow_fallback:
            # ストリーミング中はfallbackを生成せず、確定した本物のArtifactだけを描画する。
            # During streaming, never synthesize a fallback; wait for a real artifact.
            return NormalizedGenerativeResponse(
                text=text,
                parts=None,
                validation_errors=validation_errors,
            )
        fallback_text = visible_text or "UIの作成に失敗しました。通常のテキストで再試行してください。"
        if candidates or has_intent:
            fallback_artifact = _build_fallback_artifact(fallback_text, text)
            return NormalizedGenerativeResponse(
                text=fallback_text,
                parts=[
                    {"type": "text", "text": fallback_text},
                    {"type": "sandbox_artifact", "artifact": fallback_artifact},
                ],
                validation_errors=validation_errors,
            )
        return NormalizedGenerativeResponse(
            text=fallback_text,
            parts=None,
            validation_errors=validation_errors,
        )

    if not visible_text:
        visible_text = "生成UIを作成しました。" if artifacts else "ボタンを選択してください。"

    parts: list[dict[str, Any]] = [{"type": "text", "text": visible_text}]
    parts.extend({"type": "sandbox_artifact", "artifact": artifact} for artifact in artifacts)
    parts.extend({"type": "interactive_buttons", "buttons": button} for button in buttons_list)
    return NormalizedGenerativeResponse(
        text=visible_text,
        parts=parts,
        validation_errors=validation_errors,
    )
