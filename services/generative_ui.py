from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


ARTIFACT_BLOCK_RE = re.compile(
    r"```(?:chatcore-artifact|generative-ui|generative_ui|ui_artifact)(?:\s+json)?\s*"
    r"(?P<json>\{[\s\S]*?\})\s*```",
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
_JS_BANNED_TOKEN_RE = re.compile(
    r"(\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bEventSource\b|"
    r"\bnavigator\s*\.\s*sendBeacon\b|\bWorker\b|\bSharedWorker\b|"
    r"\bServiceWorker\b|\bimportScripts\b|\bimport\s*\(|\beval\s*\(|"
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


def _loads_artifact_json(raw_json: str) -> Any:
    try:
        return json.loads(raw_json)
    except json.JSONDecodeError:
        cleaned = _remove_trailing_json_commas(_strip_json_comments(raw_json))
        return json.loads(cleaned)


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


def _validate_javascript_safety(value: str) -> None:
    if _JS_BANNED_TOKEN_RE.search(value):
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
    return parts or None


def decode_message_parts(raw_parts: Any) -> list[dict[str, Any]] | None:
    return _decode_message_parts(raw_parts)


def encode_message_parts(parts: list[dict[str, Any]] | None) -> str | None:
    normalized = _decode_message_parts(parts)
    if not normalized:
        return None
    return json.dumps(normalized, ensure_ascii=False)


def normalize_response_with_artifacts(raw_text: str) -> NormalizedGenerativeResponse:
    text = raw_text if isinstance(raw_text, str) else str(raw_text or "")
    matches = list(ARTIFACT_BLOCK_RE.finditer(text))
    if not matches:
        return NormalizedGenerativeResponse(text=text, parts=None, validation_errors=[])

    artifacts: list[dict[str, Any]] = []
    validation_errors: list[str] = []
    for match in matches[:MAX_ARTIFACTS_PER_MESSAGE]:
        raw_json = match.group("json")
        try:
            payload = _loads_artifact_json(raw_json)
            artifacts.append(validate_artifact_payload(payload))
        except (json.JSONDecodeError, GenerativeUiValidationError) as exc:
            validation_errors.append(str(exc))

    visible_text = ARTIFACT_BLOCK_RE.sub("", text).strip()

    if not artifacts:
        fallback_text = visible_text or "生成UIの作成に失敗しました。通常のテキストで再試行してください。"
        return NormalizedGenerativeResponse(
            text=fallback_text,
            parts=None,
            validation_errors=validation_errors,
        )

    if not visible_text:
        visible_text = "生成UIを作成しました。"

    parts: list[dict[str, Any]] = [{"type": "text", "text": visible_text}]
    parts.extend({"type": "sandbox_artifact", "artifact": artifact} for artifact in artifacts)
    return NormalizedGenerativeResponse(
        text=visible_text,
        parts=parts,
        validation_errors=validation_errors,
    )
