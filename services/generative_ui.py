from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


ARTIFACT_BLOCK_RE = re.compile(
    r"```(?:chatcore-artifact|generative-ui|generative_ui|ui_artifact)\s*(?P<json>\{[\s\S]*?\})\s*```",
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
    r"<\s*/?\s*(script|iframe|object|embed|link|meta|base|form)\b",
    re.IGNORECASE,
)
_BANNED_EVENT_ATTR_RE = re.compile(r"\son[a-z0-9_-]+\s*=", re.IGNORECASE)
_BANNED_NAV_ATTR_RE = re.compile(
    r"\b(?:src|href|action|formaction|poster|data|xlink:href)\s*=\s*(['\"]?)\s*"
    r"(?:https?:|//|wss?:|ftp:|file:|mailto:|tel:|javascript:)",
    re.IGNORECASE,
)
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(?P<value>[^'\"\)]+)\1\s*\)", re.IGNORECASE)
_JS_BANNED_TOKEN_RE = re.compile(
    r"(\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bEventSource\b|"
    r"\bnavigator\s*\.\s*sendBeacon\b|\bWorker\b|\bSharedWorker\b|"
    r"\bServiceWorker\b|\bimportScripts\b|\bimport\s*\(|\beval\s*\(|"
    r"\bFunction\s*\(|\bdocument\s*\.\s*cookie\b|\blocalStorage\b|"
    r"\bsessionStorage\b|\bindexedDB\b|\bpostMessage\b|\bparent\b|"
    r"\btop\b|\bopener\b)",
    re.IGNORECASE,
)
_JS_NETWORK_URL_RE = re.compile(r"(?:https?:|//|wss?:|ftp:|file:|mailto:|tel:)", re.IGNORECASE)


class GenerativeUiValidationError(ValueError):
    pass


class GenerativeUiArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    version: Literal[1]
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    height: int | None = Field(default=None, ge=MIN_ARTIFACT_HEIGHT, le=MAX_ARTIFACT_HEIGHT)
    html: str = Field(default="", max_length=MAX_ARTIFACT_HTML_CHARS)
    css: str = Field(default="", max_length=MAX_ARTIFACT_CSS_CHARS)
    js: str = Field(default="", max_length=MAX_ARTIFACT_JS_CHARS)

    @field_validator("html")
    @classmethod
    def _validate_html(cls, value: str) -> str:
        if _BANNED_HTML_TAG_RE.search(value):
            raise ValueError("HTML contains a forbidden tag.")
        if _BANNED_EVENT_ATTR_RE.search(value):
            raise ValueError("HTML event handler attributes are not allowed.")
        if _BANNED_NAV_ATTR_RE.search(value):
            raise ValueError("External or executable URLs are not allowed in HTML attributes.")
        return value

    @field_validator("css")
    @classmethod
    def _validate_css(cls, value: str) -> str:
        lowered = value.lower()
        if "@import" in lowered:
            raise ValueError("CSS imports are not allowed.")
        if "</style" in lowered:
            raise ValueError("CSS cannot close the sandbox style element.")
        for match in _CSS_URL_RE.finditer(value):
            url = match.group("value").strip()
            if not (
                url.startswith("data:")
                or url.startswith("blob:")
                or url.startswith("#")
            ):
                raise ValueError("CSS URLs must be data:, blob:, or local fragment URLs.")
        return value

    @field_validator("js")
    @classmethod
    def _validate_js(cls, value: str) -> str:
        lowered = value.lower()
        if "</script" in lowered:
            raise ValueError("JavaScript cannot close the sandbox script element.")
        if _JS_BANNED_TOKEN_RE.search(value):
            raise ValueError("JavaScript uses an API that is not allowed in sandbox artifacts.")
        if _JS_NETWORK_URL_RE.search(value):
            raise ValueError("Network URLs are not allowed in sandbox JavaScript.")
        return value

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


def validate_artifact_payload(payload: Any) -> dict[str, Any]:
    try:
        artifact = GenerativeUiArtifactV1.model_validate(payload)
    except ValidationError as exc:
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
            payload = json.loads(raw_json)
            artifacts.append(validate_artifact_payload(payload))
        except (json.JSONDecodeError, GenerativeUiValidationError) as exc:
            validation_errors.append(str(exc))

    visible_text = ARTIFACT_BLOCK_RE.sub("", text).strip()

    if not artifacts:
        fallback_text = visible_text or "生成UIの作成に失敗しました。通常のテキストで再試行してください。"
        if validation_errors and visible_text:
            fallback_text = f"{fallback_text}\n\n（生成UIは安全検証に失敗したため表示しませんでした。）"
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
