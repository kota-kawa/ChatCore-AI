"""Incremental native-UI decoding and text fallback, independent of LLM providers."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from html import escape
from typing import Any

from pydantic import ValidationError

from services.error_messages import ERROR_STRUCTURED_UI_UNAVAILABLE
from services.i18n import translate_text
from services.interactive_buttons import is_markdown_code_position
from services.structured_ui_models import (
    MAX_UI_BLOCKS,
    MAX_UI_BYTES,
    MAX_UI_CHART_POINTS,
    MAX_UI_NODES,
    MAX_UI_REPLY_BYTES,
    StructuredUiV1,
    UiSource,
    declared_chart_points,
)

UI_FENCE = "```chatcore-ui"
_UI_HEADER = r"(?m)^ {0,3}```[ \t]*chatcore[ _-]*ui\b[^\n]*"
_UI_OPEN = re.compile(_UI_HEADER + r"\n", re.I)
_UI_START = re.compile(_UI_HEADER, re.I)
UI_FALLBACK = ERROR_STRUCTURED_UI_UNAVAILABLE


def has_structured_ui_source(text: str) -> bool:
    return _UI_START.search(text) is not None


def validate_structured_ui(payload: Any) -> dict[str, Any]:
    if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_UI_BYTES:
        raise ValueError("UI block too large")
    return StructuredUiV1.model_validate(payload).model_dump(exclude_none=True)


def ui_fallback(payload: Any) -> str:
    value = payload.get("fallback_text") if isinstance(payload, dict) else None
    text = value if isinstance(value, str) and 0 < len(value) <= 4000 else str(translate_text(UI_FALLBACK))
    # Legacy text renderers allow Markdown images; a native fallback must not create resource requests.
    return escape(text).replace("![", r"\![")


def project_ui_payload(payload: Any) -> Any:
    """Downgrade at the delivery boundary, never in stored/replayed canonical events."""
    if isinstance(payload, list):
        return [project_ui_payload(item) for item in payload]
    if isinstance(payload, dict):
        if payload.get("type") == "structured_ui":
            ui = payload.get("ui")
            fallback = ui_fallback(ui)
            if isinstance(ui, dict):
                raw_sources = ui.get("sources")
                if isinstance(raw_sources, list):
                    for index, raw_source in enumerate(raw_sources[:10], 1):
                        try:
                            source = UiSource.model_validate(raw_source)
                        except ValidationError:
                            continue
                        # Autolinks preserve the destination without interpreting citation titles as Markdown.
                        title = re.sub(r"([\[\]()*_\x60])", r"\\\1", escape(source.title))
                        url = source.url.replace("<", "%3C").replace(">", "%3E")
                        fallback += f"\n\n[{index}] {title} — <{url}>"
            return {"type": "text", "text": fallback}
        return {key: project_ui_payload(value) for key, value in payload.items()}
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


@dataclass
class StructuredUiStream:
    """Consume each character once; only complete blocks enter the validation boundary."""

    segments: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pending: str = ""
    in_block: bool = False
    oversized: bool = False
    seen: int = 0
    total_bytes: int = 0
    total_nodes: int = 0
    total_points: int = 0
    markdown_context: str = ""

    def _text(self, value: str) -> str:
        if value:
            if self.segments and self.segments[-1]["type"] == "text":
                self.segments[-1]["text"] += value
            else:
                self.segments.append({"type": "text", "text": value})
        return value

    def _accept(self, source: str) -> None:
        self.seen += 1
        payload: Any = None
        try:
            payload = json.loads(source, object_pairs_hook=_unique_object)
            if self.seen > 60:
                raise ValueError("Too many UI updates")
            if isinstance(payload, dict) and (payload.get("images") or payload.get("sources")):
                raise ValueError("Resolved image and citation references are server-owned")
            ui = validate_structured_ui(payload)
            previous = next((i for i, old in enumerate(self.segments) if old.get("ui", {}).get("id") == ui["id"]), None)
            old = self.segments[previous]["ui"] if previous is not None else None
            block_count = sum(part["type"] == "structured_ui" for part in self.segments) + (previous is None)
            total_nodes = self.total_nodes - (len(old["nodes"]) if old else 0) + len(ui["nodes"])
            size = len(json.dumps(ui, ensure_ascii=False, separators=(",", ":")).encode())
            old_size = len(json.dumps(old, ensure_ascii=False, separators=(",", ":")).encode()) if old else 0
            total_bytes = self.total_bytes - old_size + size
            total_points = self.total_points - (declared_chart_points(old) if old else 0) + declared_chart_points(ui)
            if (
                block_count > MAX_UI_BLOCKS
                or total_bytes > MAX_UI_REPLY_BYTES
                or total_nodes > MAX_UI_NODES
                or total_points > MAX_UI_CHART_POINTS
            ):
                raise ValueError("UI reply limit exceeded")
            self.total_nodes, self.total_bytes, self.total_points = total_nodes, total_bytes, total_points
            part = {"type": "structured_ui", "ui": ui}
            if previous is None:
                self.segments.append(part)
            else:
                self.segments[previous] = part
        except ValueError, TypeError, RecursionError, ValidationError:
            self.errors.append("structured_ui_validation_failed")
            self.segments.append(
                {"type": "ui_error", "text": ui_fallback(payload), "block_id": payload.get("id") if isinstance(payload, dict) else None}
            )

    def feed(self, chunk: str, *, final: bool = False) -> str:
        self.pending += chunk
        output: list[str] = []
        while self.pending:
            if self.in_block:
                # A closing fence is a line of its own, so backticks in JSON strings are inert.
                close = re.search(r"(?m)^ {0,3}```[ \t]*(?:\r?\n|$)", self.pending)
                if close is not None and close.end() == len(self.pending) and not self.pending.endswith("\n") and not final:
                    break
                if close is None:
                    if len(self.pending.encode()) > MAX_UI_BYTES:
                        self.oversized = True
                        self.pending = self.pending[-8:]
                    break
                body, self.pending = self.pending[: close.start()], self.pending[close.end() :]
                if self.oversized:
                    self.errors.append("structured_ui_limit_exceeded")
                    self.segments.append({"type": "ui_error", "text": translate_text(UI_FALLBACK), "block_id": None})
                else:
                    self._accept(body)
                self.in_block = self.oversized = False
                continue
            opening = _UI_OPEN.search(self.pending)
            if opening:
                context = self.markdown_context + self.pending
                position = len(self.markdown_context) + opening.start()
                if is_markdown_code_position(context, position):
                    end = opening.end()
                    prose = self.pending[:end]
                    output.append(self._text(prose))
                    self.markdown_context += prose
                    self.pending = self.pending[end:]
                    continue
                prose = self.pending[: opening.start()]
                output.append(self._text(prose))
                self.markdown_context += prose
                self.pending = self.pending[opening.end() :]
                self.in_block = True
                continue
            # Hold the last incomplete line only when it could open a UI fence.
            last_line = self.pending.rsplit("\n", 1)[-1]
            stripped = last_line.lstrip()
            candidate = re.sub(r"^```[ \t]*", "```", stripped.lower())
            candidate = re.sub(r"chatcore[ _-]*", "chatcore-", candidate, count=1)
            maybe_open = (
                bool(stripped)
                and len(last_line) - len(last_line.lstrip(" ")) <= 3
                and (UI_FENCE.startswith(candidate) or candidate.startswith(UI_FENCE))
            )
            line_position = len(self.markdown_context) + len(self.pending) - len(last_line)
            maybe_open = maybe_open and not is_markdown_code_position(self.markdown_context + self.pending, line_position)
            if final and maybe_open:
                prose = self.pending[: -len(last_line)]
                output.append(self._text(prose))
                self.errors.append("structured_ui_incomplete")
                self.segments.append({"type": "ui_error", "text": translate_text(UI_FALLBACK), "block_id": None})
                self.pending = ""
                break
            keep = len(last_line) if maybe_open else 0
            prose = self.pending[:-keep] if keep else self.pending
            if prose:
                output.append(self._text(prose))
                self.markdown_context += prose
            self.pending = self.pending[-keep:] if keep else ""
            break
        if final:
            if self.in_block or self.pending:
                self.errors.append("structured_ui_incomplete")
                self.segments.append({"type": "ui_error", "text": translate_text(UI_FALLBACK), "block_id": None})
            self.pending = ""
            self.in_block = False
        return "".join(output)

    def parts(self) -> list[dict[str, Any]]:
        return deepcopy(self.segments)


def split_structured_ui(text: str, *, final: bool = True) -> StructuredUiStream:
    stream = StructuredUiStream()
    stream.feed(text, final=final)
    return stream


def is_text_only_request(text: str) -> bool:
    return bool(re.search(r"(?:テキスト|文章|文字|言葉)(?:だけ|のみ)|(?:text|prose|words)[\s-]*only", text, re.I))


def buttons_as_text(buttons_list: list[dict[str, Any]]) -> str:
    blocks = []
    for buttons in buttons_list:
        options = buttons.get("options") or ["はい / Yes", "いいえ / No"]
        blocks.append(
            "\n\n"
            + ui_fallback({"fallback_text": buttons["question"]})
            + "\n"
            + "\n".join("- " + ui_fallback({"fallback_text": item}) for item in options)
        )
    return "".join(blocks)
