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
# モデルがフェンス名の前後に空白・記号を加えると、正規の Artifact としては
# 解釈できない。それでも定義ブロックを本文へ流すのは避けるため、表示から除く
# 範囲だけを検出する（この正規表現自体は Artifact として実行しない）。
# Models occasionally add whitespace or punctuation around a fence name. Such a
# block cannot be parsed as a real Artifact, but must still be removed from the
# visible prose. This pattern only identifies spans to discard; it never makes
# the content executable.
MALFORMED_ARTIFACT_FENCE_RE = re.compile(
    r"```[^\n`]*(?:chatcore[\s_-]*artifact|generative[\s_-]*ui|ui[\s_-]*artifact)"
    r"[^\n`]*(?:\n[\s\S]*?(?:```|\Z))",
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
# サンドボックスで利用できるローカル配信ライブラリの正規名。
# Canonical names of locally served libraries available inside the sandbox.
SUPPORTED_ARTIFACT_LIBRARIES = ("three",)
# モデル出力の表記ゆれ（three.js / threejs 等）を正規名へ寄せるためのエイリアス表。
# Alias table folding model-output spelling variants (three.js / threejs etc.)
# into canonical library names.
_ARTIFACT_LIBRARY_ALIASES = {
    "three": "three",
    "three.js": "three",
    "threejs": "three",
    "three_js": "three",
}
# モデルが libraries を書き忘れても THREE を使う JS から three 依存を推定するための検出。
# Detect THREE usage in JS so the three dependency is inferred even when the
# model forgets to declare "libraries".
_THREE_USAGE_RE = re.compile(r"\bTHREE\s*[.\[(]")
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
# 出力打ち切りで `>` まで届かなかった禁止タグの残骸。除去しないと banned-tag 検査で
# Artifact 全体が拒否されてしまう。
# Remnant of a banned tag whose `>` was cut off by output truncation. Without removal
# the banned-tag check rejects the whole artifact.
_TRUNCATED_BLOCKED_TAG_RE = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|link|meta|base)\b[^>]*\Z",
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
    r'"(?:artifact|version|title|name|label|height|description|summary|caption|libraries)"\s*:',
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
    # `.` 直後の parent/top/opener は他オブジェクトのプロパティ参照（rect.top / node.parent 等）
    # なので許可し、裸の parent./top./opener.（window暗黙参照）だけを禁止する。
    # parent/top/opener right after `.` is a property access on another object
    # (rect.top / node.parent etc.), so only bare parent./top./opener. (implicit
    # window references) are banned.
    r"(?<![\w$.])(?:parent|top|opener)\s*\.|"
    r"\bpostMessage\s*\(|"
    r"\b(?:window|document)\s*\.\s*location\b|"
    r"(?<![\w$])location\s*(?:=|\.|\[))",
    re.IGNORECASE,
)
# 生成UIのバリデーションエラーを表すカスタム例外クラスです。
# Custom exception class representing a validation error for generative UI.
class GenerativeUiValidationError(ValueError):
    pass


# 応答から抽出された、生成UIアーティファクトの候補となる生JSONと位置情報を保持するデータクラスです。
# Data class holding raw JSON and span position of extracted sandbox UI artifact candidates.
@dataclass(frozen=True)
class _ArtifactCandidate:
    raw_json: str
    span: tuple[int, int]


# バージョン1のインタラクティブボタン（Yes/No、複数選択など）のスキーマを定義するPydanticモデルクラスです。
# Pydantic model class defining the schema for version 1 interactive buttons.
class InteractiveButtonsV1(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    type: Literal["yes_no", "multiple_choice"]
    question: str = Field(min_length=1, max_length=500)
    options: list[str] | None = Field(default=None, max_length=10)

    # 選択タイプが「複数選択」の場合に、optionsリストが空でないことを検証します。
    # Validate that options are provided and non-empty when the button type is multiple_choice.
    @model_validator(mode="after")
    def _validate_options(self) -> "InteractiveButtonsV1":
        if self.type == "multiple_choice" and not self.options:
            raise ValueError("options is required for multiple_choice")
        if self.options:
            self.options = [opt for opt in self.options if opt.strip()]
        return self


# 生成UIのサンドボックスアーティファクト（HTML、CSS、JS）のスキーマを定義し、検証するPydanticモデルクラスです。
# Pydantic model class defining and validating sandbox artifact fields (HTML, CSS, JS) for version 1.
class GenerativeUiArtifactV1(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    version: Literal[1] = 1
    title: str = Field(default="生成UI", min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    height: int | None = Field(default=None, ge=MIN_ARTIFACT_HEIGHT, le=MAX_ARTIFACT_HEIGHT)
    libraries: list[Literal["three"]] | None = Field(default=None, max_length=4)
    html: str = Field(default="", max_length=MAX_ARTIFACT_HTML_CHARS)
    css: str = Field(default="", max_length=MAX_ARTIFACT_CSS_CHARS)
    js: str = Field(default="", max_length=MAX_ARTIFACT_JS_CHARS)

    # HTMLコンテンツ内のサニタイズ処理および、scriptやiframeなどの禁止タグが含まれていないかを検証します。
    # Validate and sanitize HTML content, ensuring no prohibited tags (e.g. script, iframe) are present.
    @field_validator("html")
    @classmethod
    def _validate_html(cls, value: str) -> str:
        sanitized = _sanitize_html(value)
        if _BANNED_HTML_TAG_RE.search(sanitized):
            raise ValueError("HTML contains a forbidden tag.")
        return sanitized

    # CSS定義をサニタイズし、危険なURLインポートや@importルールを除去します。
    # Sanitize CSS content to remove hazardous URL schemes or @import rules.
    @field_validator("css")
    @classmethod
    def _validate_css(cls, value: str) -> str:
        return _sanitize_css(value)

    # JavaScriptコード内の安全性を検証し、不完全なscriptタグ終了をクリーンアップします。
    # Validate the safety of JavaScript fragments and sanitize unclosed script tag remnants.
    @field_validator("js")
    @classmethod
    def _validate_js(cls, value: str) -> str:
        sanitized = _sanitize_script_end(value)
        _validate_javascript_safety(sanitized)
        return sanitized

    # HTML、CSS、JavaScript of the total character length.
    # Validate that the combined character length of HTML, CSS, and JS does not exceed the limit.
    @model_validator(mode="after")
    def _validate_total_size(self) -> "GenerativeUiArtifactV1":
        if len(self.html) + len(self.css) + len(self.js) > MAX_ARTIFACT_TOTAL_CHARS:
            raise ValueError("Sandbox artifact is too large.")
        return self


# 生成UI要素やボタンをパース・抽出した後の、正規化されたLLM応答データを保持するデータクラスです。
# Data class holding the normalized LLM response data after parsing and extracting UI artifacts.
@dataclass(frozen=True)
class NormalizedGenerativeResponse:
    text: str
    parts: list[dict[str, Any]] | None
    validation_errors: list[str]


# 値を安全に文字列型に変換します。Noneの場合は空文字を返します。
# Safely coerce the given value into a string, returning an empty string if None.
def _coerce_string(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


# 値をピクセル単位の高さ(整数)にパースし、既定の最小値〜最大値の範囲にクランプします。
# Coerce and clamp the height value to be within the allowed minimum and maximum pixel boundaries.
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


# 各コード（HTML、CSS、JS）が制限文字数を超えている場合に、優先順位に従って切り詰めます。
# Trim HTML, CSS, and JS contents sequentially to enforce the maximum aggregate limit.
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


# HTML本文が空の場合に、JavaScriptからDOM操作ができるようデフォルトのコンテナ要素を挿入します。
# Inject a default fallback container element if the HTML body is empty but JS refers to #app.
def _ensure_artifact_has_body(html: str, js: str) -> str:
    if html.strip():
        return html
    if "getElementById('app')" in js or 'getElementById("app")' in js:
        return '<div id="app"></div>'
    return '<div id="app" class="chatcore-generated-root"></div>'


# JSON文字列から、C言語風の1行コメント(//)およびブロックコメント(/* */)を除去します。
# Strip single-line and multi-line comments from the JSON-like source string.
def _strip_json_comments(source: str) -> str:
    output: list[str] = []
    in_string = False
    quote = ""
    escaped = False
    index = 0
    # 文字列リテラル内の // や /* */ はコンテンツとして残し、JSON 外側のコメントだけを削ります。
    # Keep // or /* */ within string literals as content, stripping only comments outside JSON structures.
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


# JSONの末尾にある不要なカンマ（配列やオブジェクトの閉じ括弧の前）を除去します。
# Remove trailing commas before closing braces/brackets in the JSON string.
def _remove_trailing_json_commas(source: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", source)


# JSON文字列に含まれるバックスラッシュによる行継続文字を除去します。
# Strip backslash line continuation sequences from the JSON source.
def _remove_json_line_continuations(source: str) -> str:
    return re.sub(r"\\[ \t]*(?:\r\n|\r|\n)[ \t]*", "", source)


# JSON文字列リテラル内の生改行コードを、エスケープされた改行シーケンス(\n)に置換します。
# Escape raw newlines inside JSON string literals into escaped newline sequences (\n).
def _escape_json_string_newlines(source: str) -> str:
    output: list[str] = []
    in_string = False
    escaped = False
    index = 0
    # モデル出力では JSON 文字列内に生改行が混ざることがあるため、文字列の外側は触らず、内側の改行だけを JSON として読める形に変換します。
    # Since raw newlines might be mixed in JSON strings in model outputs, convert only internal newlines into a format readable as JSON without touching the outside of strings.
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


# JSON形式のテキストを正規化して、標準的なJSONパーサでパースできるように前処理を行います。
# Pre-process and normalize a JSON-like source string to make it compliant with standard JSON parsers.
def _normalize_jsonish_source(source: str) -> str:
    return _remove_trailing_json_commas(
        _strip_json_comments(
            _escape_json_string_newlines(
                _remove_json_line_continuations(source)
            )
        )
    )


# テキストをJSONオブジェクトとしてロードします。パース失敗時は正規化を施した上で再試行します。
# Load JSON object from text, retrying with normalized source on initial parsing failure.
def _loads_artifact_json(raw_json: str) -> Any:
    try:
        return json.loads(raw_json)
    except json.JSONDecodeError:
        # strict=False は文字列内の生の制御文字（タブ等）を許容する。モデル出力では
        # コード断片が未エスケープのまま混ざることがあるため、リトライ側だけ緩める。
        # strict=False tolerates raw control characters (tabs etc.) inside strings.
        # Model outputs sometimes embed unescaped code fragments, so only the retry
        # path is relaxed.
        return json.loads(_normalize_jsonish_source(raw_json), strict=False)


# 2つの文字列スパンが重複しているかどうかを判定します。
# Check whether two character spans overlap with each other.
def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


# 対象のスパンが、既に登録済みのスパンリストのいずれかと重複しているかを判定します。
# Check whether the target span overlaps with any of the registered spans.
def _span_overlaps_any(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(_spans_overlap(span, existing) for existing in spans)


# テキストが生成UIアーティファクト定義のJSONであるらしい特徴（特定のキーの有無）を備えているかをチェックします。
# Inspect if the text looks like a valid sandbox artifact JSON by verifying key characteristics.
def _looks_like_artifact_json(source: str) -> bool:
    source_keys = {match.group("key").lower() for match in _ARTIFACT_SOURCE_KEY_RE.finditer(source)}
    return bool(source_keys) and (len(source_keys) >= 2 or bool(_ARTIFACT_CONTEXT_KEY_RE.search(source)))


# 本文から、ネストを含むWeb検索結果ソースのdetailsタグブロックをすべて除去します。
# Strip nested Web search source details blocks from the raw text.
def _strip_web_search_sources_html(text: str) -> str:
    if "web-search-sources" not in text:
        return text
    # ネストした details を含まない最も内側のブロックから順に除去し、変化が無くなるまで
    # 繰り返すことで外側のトレースブロックも安全に取り除く。
    # Remove the innermost blocks first and repeat until stable so nested trace
    # blocks are stripped safely as well.
    current = text
    # 正規表現だけではネスト全体を一度に消せないため、内側から消して安定するまで繰り返します。
    # Since regular expressions alone cannot remove the entire nest at once, repeat removing from the inside until it stabilizes.
    while True:
        stripped = _WEB_SEARCH_SOURCES_BLOCK_RE.sub("", current)
        if stripped == current:
            return current
        current = stripped


# 本文の最初の空でない行などから、アーティファクトのタイトルを推測します。
# Infer a title for the sandbox artifact from the surrounding prose.
def _infer_artifact_title(text: str) -> str:
    cleaned = FENCED_BLOCK_RE.sub("", _strip_web_search_sources_html(text)).strip()
    for line in cleaned.splitlines():
        line = line.strip(" #:-\t")
        if line:
            return line[:60]
    return "生成UI"


# 本文のテキストから、モデルが明示的または暗示的に生成UIを作成しようとしていた意図があるかを判定します。
# Infer whether the model intended to produce a visual UI block from the text content.
def _has_artifact_intent(text: str) -> bool:
    stripped = FENCED_BLOCK_RE.sub("", _strip_web_search_sources_html(text)).strip()
    if _STRONG_ARTIFACT_INTENT_RE.search(stripped):
        return True
    if len(stripped) > _SHORT_INTENT_CHAR_LIMIT:
        return False
    return bool(
        _WEAK_ARTIFACT_INTENT_RE.search(stripped)
        or _DISPLAY_ONLY_INTENT_RE.search(stripped)
    )


# 開き括弧 { に対応する閉じ括弧 } のペアをパースし、JSONオブジェクトの終端インデックスを返します。
# Parse matched brackets to find the end position of a JSON object string.
def _find_balanced_object_end(source: str, start: int) -> int | None:
    depth = 0
    in_string = False
    quote = ""
    escaped = False
    index = start
    # raw JSON 候補を本文から拾うため、文字列内の波括弧を無視しながら対応する閉じ括弧を探します。
    # Search for the matching closing bracket while ignoring braces inside strings to collect raw JSON candidates from the text.
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


# テキストから、フェンスで囲まれていない生のJSON型アーティファクト定義の候補を検出します。
# Scan text to locate un-fenced raw JSON object candidates of sandbox artifacts.
def _find_raw_artifact_candidates(
    text: str,
    excluded_spans: list[tuple[int, int]],
    ) -> list[_ArtifactCandidate]:
    candidates: list[_ArtifactCandidate] = []
    index = 0
    # fenced code block と重なる波括弧は除外し、本文中に直接貼られた artifact JSON だけを候補にします。
    # Exclude braces that overlap with fenced code blocks, and only consider artifact JSON directly embedded in the prose as candidates.
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


# html, css, js 等の通常のソースコードブロックを合成し、生成UIアーティファクトに統合します。
# Extract and merge markdown source blocks (html/css/js) into a unified sandbox candidate.
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


# 不完全なJSONの末尾から、途切れたトークンを1つ削ります。
# Remove the last incomplete token from a truncated JSON string.
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


# 出力が途中で途切れたJSONオブジェクトを、括弧を自動的に閉じるなどして復元を試みます。
# Best-effort recovery of a JSON object that was truncated mid-stream by closing unclosed brackets.
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
            json.loads(_normalize_jsonish_source(closed), strict=False)
        except json.JSONDecodeError:
            shortened = _drop_trailing_json_token(trimmed)
            if shortened == trimmed:
                return None
            candidate = shortened
            continue
        return closed
    return None


# 途中で途切れて閉じられていないアーティファクトブロックを検出し、復元を試みます。
# Detect and attempt to restore unclosed artifact code blocks.
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


# 応答テキスト全体から、生成UIアーティファクトの候補スパンをすべて抽出してソートしたリストを返します。
# Extract all potential sandbox artifact candidates from the response prose.
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


def _extract_malformed_artifact_fence_spans(
    text: str,
    occupied_spans: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Return malformed artifact fence ranges that must not reach chat prose."""
    spans: list[tuple[int, int]] = []
    for match in MALFORMED_ARTIFACT_FENCE_RE.finditer(text):
        span = match.span()
        if _span_overlaps_any(span, [*occupied_spans, *spans]):
            continue
        spans.append(span)
    return spans


# 応答テキストから抽出されたアーティファクトの定義ブロック部分を除去（非表示化）します。
# Strip the JSON/code block sections of identified candidates from the visible prose.
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


# イテレータの中で、真と評価される最初の要素を返します。すべて偽なら None を返します。
# Find and return the first element in the iterator that evaluates to true.
def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


# 属性値の前後に存在する引用符を除去します。
# Strip surrounding single or double quotes from HTML attribute values.
def _strip_attribute_quotes(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        return value[1:-1]
    return value


# JavaScriptコード内に現れる script 閉じタグの不要な文字列を無効化します。
# Sanitize and deactivate literal closing script tags inside JavaScript blocks.
def _sanitize_script_end(value: str) -> str:
    return re.sub(r"</\s*script", r"<\\/script", value, flags=re.IGNORECASE)


# JavaScriptコードからコメントおよび文字列リテラルを除去し、安全性の解析用テキストを作成します。
# Strip comments and string literals from JavaScript to facilitate code structure safety checks.
def _strip_javascript_literals_and_comments(value: str) -> str:
    output: list[str] = []
    index = 0
    # 危険構文の検査前に、コメントや文字列中の単語をコード本体として誤検出しないよう除去します。
    # Strip comments and words inside strings to avoid false positives as code body before scanning for hazardous syntax.
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


# JavaScriptコードに危険なトークン（Cookieアクセス、外部接続、eval等）が含まれていないかチェックします。
# Ensure JavaScript is safe by looking for prohibited tokens (e.g., cookie access, network requests).
def _validate_javascript_safety(value: str) -> None:
    if _JS_BANNED_TOKEN_RE.search(_strip_javascript_literals_and_comments(value)):
        raise ValueError("JavaScript uses an API that is not allowed in sandbox artifacts.")


# 小規模なJSフラグメントの安全性を判定し、例外が発生しなければ True を返します。
# Assess if a small JS fragment is safe, returning True if no validation exceptions are raised.
def _is_safe_javascript_fragment(value: str) -> bool:
    try:
        _validate_javascript_safety(value)
    except ValueError:
        return False
    return True


# URLやリソースのURLが、安全なプロトコル（http, https等）で始まっているかを検証します。
# Validate that resource URLs use safe, allowed protocol schemes.
def _is_safe_resource_url(value: str) -> bool:
    url = value.strip()
    if not url:
        return True
    return (
        url.startswith("data:")
        or url.startswith("blob:")
        or url.startswith("#")
    )


# CSS定義から危険な @import や url() 表現を除去・サニタイズします。
# Clean CSS by removing dangerous @import rules and checking url() schemes.
def _sanitize_css(value: str) -> str:
    sanitized = _coerce_string(value)
    sanitized = re.sub(r"</\s*style", r"<\\/style", sanitized, flags=re.IGNORECASE)
    sanitized = _CSS_IMPORT_RE.sub("", sanitized)

    # CSS内の url(...) 定義に含まれる危険な外部リソースを検出し、置換します。
    # Inspect and replace url() references in CSS blocks with safe values.
    def replace_url(match: re.Match[str]) -> str:
        url = match.group("value").strip()
        if url.startswith("data:") or url.startswith("blob:") or url.startswith("#"):
            return match.group(0)
        return "url(\"data:,\")"

    return _CSS_URL_RE.sub(replace_url, sanitized)


# HTMLコンテンツ内のイベント属性（onclick等）や、href等に指定されたjavascript:スキームを無効化します。
# Strip inline event handlers and sanitize resource paths inside HTML tags.
def _sanitize_html(value: str) -> str:
    sanitized = _coerce_string(value)
    sanitized = _BLOCKED_ELEMENT_RE.sub("", sanitized)
    sanitized = _BLOCKED_TAG_RE.sub("", sanitized)
    sanitized = _TRUNCATED_BLOCKED_TAG_RE.sub("", sanitized)

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


# libraries指定の表記ゆれを正規化し、JS本文からの推定も合わせてライブラリ一覧を組み立てます。
# Normalize library declarations (folding aliases) and infer dependencies from the JS body.
def _normalize_artifact_libraries(value: Any, js: str) -> list[str]:
    if value is None:
        raw_items: list[Any] = []
    elif isinstance(value, str):
        raw_items = re.split(r"[,\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]

    libraries: list[str] = []
    for item in raw_items:
        name = _ARTIFACT_LIBRARY_ALIASES.get(str(item).strip().lower())
        if name and name not in libraries:
            libraries.append(name)
    if "three" not in libraries and _THREE_USAGE_RE.search(js):
        libraries.append("three")
    return libraries


# アーティファクト定義の辞書型データを整形し、各コードソース（HTML、CSS、JS）を適切にセットします。
# Coerce and format raw artifact dictionary fields into a standard structure.
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
    libraries = _normalize_artifact_libraries(
        _first_present(payload, "libraries", "library", "libs", "lib"), js
    )
    prepared = {
        "version": 1,
        "title": title[:120],
        "description": description[:500] if description else None,
        "height": _coerce_height(payload.get("height")),
        "html": html,
        "css": css,
        "js": js,
    }
    if libraries:
        prepared["libraries"] = libraries
    if prepared["description"] is None:
        prepared.pop("description")
    return prepared


# アーティファクトデータの値をパース・検証し、バリデーション済みの辞書型を返します。
# Validate raw dictionary properties of the sandbox artifact against version 1 schema.
def validate_artifact_payload(payload: Any) -> dict[str, Any]:
    try:
        artifact = GenerativeUiArtifactV1.model_validate(_prepare_artifact_payload(payload))
    except ValidationError as exc:
        raise GenerativeUiValidationError(str(exc)) from exc
    except ValueError as exc:
        raise GenerativeUiValidationError(str(exc)) from exc
    return artifact.model_dump(exclude_none=True)


# インタラクティブボタンの定義データをバリデーションして返します。
# Validate interactive buttons structure using Pydantic model.
def validate_interactive_buttons_payload(payload: Any) -> dict[str, Any]:
    try:
        buttons = InteractiveButtonsV1.model_validate(payload)
    except ValidationError as exc:
        raise GenerativeUiValidationError(str(exc)) from exc
    except ValueError as exc:
        raise GenerativeUiValidationError(str(exc)) from exc
    return buttons.model_dump(exclude_none=True)


# メッセージパーツのリスト（テキスト、生成UI、ボタン等）をデコード・検証して返します。
# Parse and decode structured message parts from JSON or raw payloads.
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


# メッセージパーツのリスト（テキスト、生成UI、ボタン等）をデコード・検証して返します。
# Parse and decode structured message parts from JSON or raw payloads.
def decode_message_parts(raw_parts: Any) -> list[dict[str, Any]] | None:
    return _decode_message_parts(raw_parts)


# メッセージパーツのリストをJSON文字列にシリアライズします。
# Serialize the list of message parts to a JSON string.
def encode_message_parts(parts: list[dict[str, Any]] | None) -> str | None:
    normalized = _decode_message_parts(parts)
    if not normalized:
        return None
    return json.dumps(normalized, ensure_ascii=False)


# モデルがアーティファクト出力に失敗した際、本文中に埋め込まれたHTMLコード等を回収してフォールバック用のUIを組み立てます。
# Recover un-fenced markup or scripts from prose to synthesize a fallback sandbox UI card.
def _build_fallback_artifact(visible_text: str, raw_text: str) -> dict[str, Any]:
    title = _infer_artifact_title(visible_text or raw_text)
    # Web検索のトレースブロックHTMLがエスケープされてカード本文に流れ込むのを防ぐ。
    # Keep the web-search trace markup out of the escaped card body.
    source_text = _strip_web_search_sources_html(
        visible_text or raw_text or "生成UIを表示するための内容を補完しました。"
    ).strip()
    if not source_text:
        source_text = "生成UIを表示するための内容を補完しました。"
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


# 応答テキストから生成UIとボタンの構成要素を抽出・分離し、ユーザーに見せるテキストと構造化パーツリストに分割します。
# Parse the raw response prose to isolate UI blocks and buttons, returning a normalized text and parts list.
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

    all_candidates = sorted(candidates + button_candidates, key=lambda c: c.span)
    malformed_fence_spans = _extract_malformed_artifact_fence_spans(
        text,
        [candidate.span for candidate in all_candidates],
    )
    has_intent = _has_artifact_intent(text)
    if not candidates and not button_candidates and not has_intent and not malformed_fence_spans:
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

    visible_candidates = [
        *all_candidates,
        *(_ArtifactCandidate(raw_json="", span=span) for span in malformed_fence_spans),
    ]
    visible_text = _remove_candidate_spans(text, visible_candidates)

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
