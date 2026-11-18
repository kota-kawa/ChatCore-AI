"""Check that a native answer actually supports the operation the user requested."""

from __future__ import annotations

import re
from typing import Any

from services.generative_ui_intent import requests_interactive_operation

_CALCULATION = re.compile(r"計算|試算|ローン|返済|貯蓄|金利|\b(?:calculat\w*|loan|mortgage|savings?|interest)\b", re.I)


def requested_native_quality_issues(parts: list[dict[str, Any]] | None, user_request: str) -> list[str]:
    if not requests_interactive_operation(user_request):
        return []
    documents = [part["ui"] for part in parts or [] if part.get("type") == "structured_ui"]
    if not documents:
        return []
    nodes = [node for ui in documents for node in ui["nodes"]]
    controls = [
        node for node in nodes if node["type"] in {"input", "textarea", "slider", "select", "checkbox", "button", "choice", "tabs", "steps"}
    ]
    if not controls:
        return ["structured_ui_interaction_missing"]
    if not _CALCULATION.search(user_request):
        return []
    if any(_has_connected_calculation(ui) for ui in documents):
        return []
    return ["structured_ui_calculation_not_connected"]


def _has_connected_calculation(ui: dict[str, Any]) -> bool:
    """A calculator needs state-dependent output and chart series, not decorative controls."""
    expressions = {expression["id"]: expression for expression in ui.get("expressions", [])}
    numeric_states = {
        node["state_id"]
        for node in ui["nodes"]
        if node["type"] == "slider" or (node["type"] == "input" and node.get("input_type") == "number")
    }

    dependency_cache: dict[str, bool] = {}

    def depends_on_input(expression_id: str, visited: set[str]) -> bool:
        if expression_id in visited or expression_id not in expressions:
            return False
        if expression_id in dependency_cache:
            return dependency_cache[expression_id]
        for arg in expressions[expression_id]["args"]:
            if arg.get("kind") == "state" and arg.get("value") in numeric_states:
                dependency_cache[expression_id] = True
                return True
            if arg.get("kind") == "expression" and depends_on_input(str(arg.get("value")), visited | {expression_id}):
                dependency_cache[expression_id] = True
                return True
        dependency_cache[expression_id] = False
        return False

    display_updates = any(
        node.get("binding") and depends_on_input(node["binding"], set())
        for node in ui["nodes"]
        if node["type"] in {"text", "heading", "markdown"}
    )
    chart_updates = any(
        series.get("binding") and depends_on_input(series["binding"], set())
        for node in ui["nodes"]
        if node["type"] == "chart"
        for series in node["series"]
    )
    return bool(numeric_states and display_updates and chart_updates)
