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
_ARTIFACT_INTENT_RE = re.compile(
    r"(chatcore-artifact|generative ui|生成UI|artifact|"
    r"可視化|図解|インフォグラフィック|ダッシュボード|チャート|グラフ|"
    r"タイムライン|フローチャート|比較表|カードビュー)",
    re.IGNORECASE,
)
_DISPLAY_ONLY_INTENT_RE = re.compile(
    r"(表示します|表示しました|作成します|作成しました|用意しました|以下に示します)",
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
class GenerativeUiValidationError(ValueError):
    pass


@dataclass(frozen=True)
class _ArtifactCandidate:
    raw_json: str
    span: tuple[int, int]


class InteractiveButtonsV1(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    type: Literal["yes_no", "multiple_choice"]
    question: str = Field(min_length=1, max_length=500)
    options: list[str] | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def _validate_options(self) -> "InteractiveButtonsV1":
        if self.type == "multiple_choice" and not self.options:
            raise ValueError("options is required for multiple_choice")
        if self.options:
            self.options = [opt for opt in self.options if opt.strip()]
        return self


class GenerativeUiArtifactV1(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    version: Literal[1] = 1
    title: str = Field(default="生成UI", min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    height: int | None = Field(default=None, ge=MIN_ARTIFACT_HEIGHT, le=MAX_ARTIFACT_HEIGHT)
    html: str = Field(default="", max_length=MAX_ARTIFACT_HTML_CHARS)
    css: str = Field(default="", max_length=MAX_ARTIFACT_CSS_CHARS)
    js: str = Field(default="", max_length=MAX_ARTIFACT_JS_CHARS)

    @field_validator("html")
    @classmethod
    def _validate_html(cls, value: str) -> str:
        sanitized = _sanitize_html(value)
        if _BANNED_HTML_TAG_RE.search(sanitized):
            raise ValueError("HTML contains a forbidden tag.")
        return sanitized

    @field_validator("css")
    @classmethod
    def _validate_css(cls, value: str) -> str:
        return _sanitize_css(value)

    @field_validator("js")
    @classmethod
    def _validate_js(cls, value: str) -> str:
        sanitized = _sanitize_script_end(value)
        _validate_javascript_safety(sanitized)
        return sanitized

    @model_validator(mode="after")
    def _validate_total_size(self) -> "GenerativeUiArtifactV1":
        if len(self.html) + len(self.css) + len(self.js) > MAX_ARTIFACT_TOTAL_CHARS:
            raise ValueError("Sandbox artifact is too large.")
        return self


@dataclass(frozen=True)
class NormalizedGenerativeResponse:
    text: str
    parts: list[dict[str, Any]] | None
    validation_errors: list[str]


def _coerce_string(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _coerce_height(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if not match:
            return None
        value = int(match.group(0))
    if isinstance(value, (int, float)):
        return min(max(int(value), MIN_ARTIFACT_HEIGHT), MAX_ARTIFACT_HEIGHT)
    return None


def _trim_artifact_sources(html: str, css: str, js: str) -> tuple[str, str, str]:
    html = html[:MAX_ARTIFACT_HTML_CHARS]
    css = css[:MAX_ARTIFACT_CSS_CHARS]
    js = js[:MAX_ARTIFACT_JS_CHARS]
    overflow = len(html) + len(css) + len(js) - MAX_ARTIFACT_TOTAL_CHARS
    if overflow <= 0:
        return html, css, js

    js_trim = min(len(js), overflow)
    js = js[: len(js) - js_trim]
    overflow -= js_trim
    if overflow <= 0:
        return html, css, js

    css_trim = min(len(css), overflow)
    css = css[: len(css) - css_trim]
    overflow -= css_trim
    if overflow <= 0:
        return html, css, js

    html = html[: max(0, len(html) - overflow)]
    return html, css, js


def _ensure_artifact_has_body(html: str, js: str) -> str:
    if html.strip():
        return html
    if "getElementById('app')" in js or 'getElementById("app")' in js:
        return '<div id="app"></div>'
    return '<div id="app" class="chatcore-generated-root"></div>'


def _strip_json_comments(source: str) -> str:
    output: list[str] = []
    in_string = False
    quote = ""
    escaped = False
    index = 0
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


def _remove_trailing_json_commas(source: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", source)


def _remove_json_line_continuations(source: str) -> str:
    return re.sub(r"\\[ \t]*(?:\r\n|\r|\n)[ \t]*", "", source)


def _escape_json_string_newlines(source: str) -> str:
    output: list[str] = []
    in_string = False
    escaped = False
    index = 0
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


def _normalize_jsonish_source(source: str) -> str:
    return _remove_trailing_json_commas(
        _strip_json_comments(
            _escape_json_string_newlines(
                _remove_json_line_continuations(source)
            )
        )
    )


def _loads_artifact_json(raw_json: str) -> Any:
    try:
        return json.loads(raw_json)
    except json.JSONDecodeError:
        return json.loads(_normalize_jsonish_source(raw_json))


def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _span_overlaps_any(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(_spans_overlap(span, existing) for existing in spans)


def _looks_like_artifact_json(source: str) -> bool:
    source_keys = {match.group("key").lower() for match in _ARTIFACT_SOURCE_KEY_RE.finditer(source)}
    return bool(source_keys) and (len(source_keys) >= 2 or bool(_ARTIFACT_CONTEXT_KEY_RE.search(source)))


def _infer_artifact_title(text: str) -> str:
    cleaned = FENCED_BLOCK_RE.sub("", text).strip()
    for line in cleaned.splitlines():
        line = line.strip(" #:-\t")
        if line:
            return line[:60]
    return "生成UI"


def _has_artifact_intent(text: str) -> bool:
    stripped = FENCED_BLOCK_RE.sub("", text).strip()
    if _ARTIFACT_INTENT_RE.search(stripped):
        return True
    return len(stripped) <= 180 and bool(_DISPLAY_ONLY_INTENT_RE.search(stripped))


def _find_balanced_object_end(source: str, start: int) -> int | None:
    depth = 0
    in_string = False
    quote = ""
    escaped = False
    index = start
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


def _find_raw_artifact_candidates(
    text: str,
    excluded_spans: list[tuple[int, int]],
) -> list[_ArtifactCandidate]:
    candidates: list[_ArtifactCandidate] = []
    index = 0
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


def _extract_source_code_artifact_candidates(
    text: str,
    occupied_spans: list[tuple[int, int]],
) -> list[_ArtifactCandidate]:
    blocks: list[tuple[str, str, tuple[int, int]]] = []
    for match in SOURCE_CODE_BLOCK_RE.finditer(text):
        span = match.span()
        if _span_overlaps_any(span, occupied_spans):
            continue
        blocks.append((match.group("lang").lower(), match.group("code").strip(), span))

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


def _drop_trailing_json_token(source: str) -> str:
    # 末尾の不完全なトークン（文字列・数値・リテラル）を1つ取り除く。
    # Drop one trailing JSON token (string / number / literal) so a truncated
    # remainder can be closed into a valid object.
    match = re.search(
        r'(?:"(?:[^"\\]|\\.)*"|[-+0-9.eE]+|true|false|null)\s*$',
        source,
    )
    if match:
        return source[: match.start()].rstrip()
    return source[:-1].rstrip()


def _repair_truncated_json(source: str) -> str | None:
    # 出力が途中で打ち切られたJSONオブジェクトを最大限復元する。開いた文字列・括弧を
    # 閉じ、末尾の不完全なトークンや区切り文字を削ってから検証する。
    # Best-effort completion of a JSON object whose output was cut off mid-stream.
    start = source.find("{")
    if start == -1:
        return None

    stack: list[str] = []
    in_string = False
    escaped = False
    quote = ""
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


def _extract_artifact_candidates(
    text: str,
    *,
    recover_truncated: bool = False,
) -> list[_ArtifactCandidate]:
    candidates: list[_ArtifactCandidate] = []
    occupied_spans: list[tuple[int, int]] = []

    for match in ARTIFACT_BLOCK_RE.finditer(text):
        candidate = _ArtifactCandidate(raw_json=match.group("json"), span=match.span())
        candidates.append(candidate)
        occupied_spans.append(candidate.span)

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


def _remove_candidate_spans(text: str, candidates: list[_ArtifactCandidate]) -> str:
    if not candidates:
        return text.strip()
    pieces: list[str] = []
    cursor = 0
    for candidate in sorted(candidates, key=lambda item: item.span):
        start, end = candidate.span
        if start < cursor:
            continue
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces).strip()


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _strip_attribute_quotes(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        return value[1:-1]
    return value


def _sanitize_script_end(value: str) -> str:
    return re.sub(r"</\s*script", r"<\\/script", value, flags=re.IGNORECASE)


def _strip_javascript_literals_and_comments(value: str) -> str:
    output: list[str] = []
    index = 0
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


def _validate_javascript_safety(value: str) -> None:
    if _JS_BANNED_TOKEN_RE.search(_strip_javascript_literals_and_comments(value)):
        raise ValueError("JavaScript uses an API that is not allowed in sandbox artifacts.")


def _is_safe_javascript_fragment(value: str) -> bool:
    try:
        _validate_javascript_safety(value)
    except ValueError:
        return False
    return True


def _is_safe_resource_url(value: str) -> bool:
    url = value.strip()
    if not url:
        return True
    return (
        url.startswith("data:")
        or url.startswith("blob:")
        or url.startswith("#")
    )


def _sanitize_css(value: str) -> str:
    sanitized = _coerce_string(value)
    sanitized = re.sub(r"</\s*style", r"<\\/style", sanitized, flags=re.IGNORECASE)
    sanitized = _CSS_IMPORT_RE.sub("", sanitized)

    def replace_url(match: re.Match[str]) -> str:
        url = match.group("value").strip()
        if url.startswith("data:") or url.startswith("blob:") or url.startswith("#"):
            return match.group(0)
        return "url(\"data:,\")"

    return _CSS_URL_RE.sub(replace_url, sanitized)


def _sanitize_html(value: str) -> str:
    sanitized = _coerce_string(value)
    sanitized = _BLOCKED_ELEMENT_RE.sub("", sanitized)
    sanitized = _BLOCKED_TAG_RE.sub("", sanitized)

    def replace_event_attr(match: re.Match[str]) -> str:
        handler = _strip_attribute_quotes(match.group("value"))
        return match.group(0) if _is_safe_javascript_fragment(handler) else ""

    def replace_style_attr(match: re.Match[str]) -> str:
        style = _strip_attribute_quotes(match.group("value"))
        return match.group(0) if _sanitize_css(style) == style else ""

    def replace_nav_attr(match: re.Match[str]) -> str:
        name = match.group("name")
        value = _strip_attribute_quotes(match.group("value"))
        if _is_safe_resource_url(value):
            return match.group(0)
        if name.lower() in {"href", "xlink:href"}:
            return f' {name}="#"'
        return ""

    sanitized = _EVENT_ATTR_RE.sub(replace_event_attr, sanitized)
    sanitized = _STYLE_ATTR_RE.sub(replace_style_attr, sanitized)
    sanitized = _NAV_ATTR_RE.sub(replace_nav_attr, sanitized)
    return sanitized


def _prepare_artifact_payload(payload: Any) -> Any:
    if isinstance(payload, list):
        payload = next((item for item in payload if isinstance(item, dict)), payload)
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

    def extract_style(match: re.Match[str]) -> str:
        embedded_css.append(match.group("body"))
        return ""

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


def validate_artifact_payload(payload: Any) -> dict[str, Any]:
    try:
        artifact = GenerativeUiArtifactV1.model_validate(_prepare_artifact_payload(payload))
    except ValidationError as exc:
        raise GenerativeUiValidationError(str(exc)) from exc
    except ValueError as exc:
        raise GenerativeUiValidationError(str(exc)) from exc
    return artifact.model_dump(exclude_none=True)


def validate_interactive_buttons_payload(payload: Any) -> dict[str, Any]:
    try:
        buttons = InteractiveButtonsV1.model_validate(payload)
    except ValidationError as exc:
        raise GenerativeUiValidationError(str(exc)) from exc
    except ValueError as exc:
        raise GenerativeUiValidationError(str(exc)) from exc
    return buttons.model_dump(exclude_none=True)


def _decode_message_parts(raw_parts: Any) -> list[dict[str, Any]] | None:
    if not raw_parts:
        return None
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


def decode_message_parts(raw_parts: Any) -> list[dict[str, Any]] | None:
    return _decode_message_parts(raw_parts)


def encode_message_parts(parts: list[dict[str, Any]] | None) -> str | None:
    normalized = _decode_message_parts(parts)
    if not normalized:
        return None
    return json.dumps(normalized, ensure_ascii=False)


def _build_fallback_artifact(visible_text: str, raw_text: str) -> dict[str, Any]:
    title = _infer_artifact_title(visible_text or raw_text)
    source_text = (visible_text or raw_text or "生成UIを表示するための内容を補完しました。").strip()
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


def normalize_response_with_artifacts(
    raw_text: str,
    *,
    recover_truncated: bool = False,
    allow_fallback: bool = True,
) -> NormalizedGenerativeResponse:
    text = raw_text if isinstance(raw_text, str) else str(raw_text or "")
    candidates = _extract_artifact_candidates(text, recover_truncated=recover_truncated)
    
    button_candidates: list[_ArtifactCandidate] = []
    for match in INTERACTIVE_BUTTONS_BLOCK_RE.finditer(text):
        button_candidates.append(_ArtifactCandidate(raw_json=match.group("json"), span=match.span()))
        
    has_intent = _has_artifact_intent(text)
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
