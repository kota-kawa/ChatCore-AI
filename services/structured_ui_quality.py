"""Check that a native answer actually supports the operation the user requested."""

from __future__ import annotations

import re
from functools import cache
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

    # The document validator has already checked references and rejected cycles.
    @cache
    def input_dependencies(expression_id: str) -> frozenset[str]:
        states: set[str] = set()
        for arg in expressions[expression_id]["args"]:
            if arg["kind"] == "state" and arg["value"] in numeric_states:
                states.add(arg["value"])
            elif arg["kind"] == "expression":
                states.update(input_dependencies(arg["value"]))
        return frozenset(states)

    display_inputs = set().union(*(
        input_dependencies(node["binding"])
        for node in ui["nodes"]
        if node["type"] in {"text", "heading"} and node.get("binding")
    ))
    chart_inputs = set().union(*(
        input_dependencies(series["binding"])
        for node in ui["nodes"]
        if node["type"] == "chart"
        for series in node["series"]
        if series.get("binding")
    ))
    return bool(display_inputs and chart_inputs) and numeric_states <= (display_inputs | chart_inputs)
