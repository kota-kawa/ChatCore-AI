"""Resolve native citations without inserting HTML into the declarative renderer."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from services.structured_ui_models import UiSource
from services.web_search import WebSearchResult, resolve_web_search_citations, strip_web_search_citation_html


def _resolve_native_citations(ui: dict[str, Any], evidence: WebSearchResult | None) -> None:
    sources: list[dict[str, Any]] = []
    source_numbers: dict[str, int] = {}

    def resolve(text: str, *, required: bool = False) -> str:
        result = resolve_web_search_citations(strip_web_search_citation_html(text), evidence)
        output = result.text
        markers: list[tuple[int, int, str]] = []
        for citation in result.citations:
            if citation.url not in source_numbers and len(sources) < 10:
                try:
                    source = UiSource(url=citation.url, title=(citation.title or citation.url)[:200])
                except ValidationError:
                    pass
                else:
                    sources.append(source.model_dump())
                    source_numbers[citation.url] = len(sources)
            number = source_numbers.get(citation.url)
            markers.append((citation.start, citation.end, f"[{number}]" if number else ""))
        for start, end, label in reversed(markers):
            output = output[:start] + label + output[end:]
        return text if required and not output.strip() else output

    ui["fallback_text"] = resolve(ui["fallback_text"], required=True)
    for node in ui["nodes"]:
        for key in ("text", "title", "caption", "label", "alt"):
            if isinstance(node.get(key), str):
                node[key] = resolve(node[key], required=key in {"label", "alt"})
        for key in ("columns", "labels"):
            if key in node and isinstance(node[key], list):
                node[key] = [resolve(label) for label in node[key]]
        if node["type"] == "table":
            node["rows"] = [[resolve(cell) if isinstance(cell, str) else cell for cell in row] for row in node["rows"]]
        for key in ("series", "items", "edges"):
            for item in node.get(key, []):
                item["label"] = resolve(item["label"], required=key == "items")
        if node["type"] == "choice":
            buttons = node["buttons"]
            buttons["question"] = resolve(buttons["question"], required=True)
            if buttons.get("options"):
                options = [resolve(option, required=True) for option in buttons["options"]]
                # Keep distinguishable choices if citation removal would collapse their labels.
                if len(set(options)) == len(options):
                    buttons["options"] = options
    ui["sources"] = sources


def resolve_message_part_citations(
    parts: list[dict[str, Any]],
    evidence: WebSearchResult | None,
) -> list[dict[str, Any]]:
    output = deepcopy(parts)
    for part in output:
        if part.get("type") == "text":
            part["text"] = resolve_web_search_citations(strip_web_search_citation_html(part["text"]), evidence).text
        elif part.get("type") == "structured_ui":
            _resolve_native_citations(part["ui"], evidence)
    return output
