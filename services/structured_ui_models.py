"""Versioned, code-free UI contract. Flat references keep JSON schemas non-recursive."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator, model_validator

from services.generative_ui_images import GenerativeUiImageV1
from services.interactive_buttons import InteractiveButtonsV1

UiScalar = StrictStr | StrictInt | StrictFloat | StrictBool
UiId = Annotated[str, Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")]
MAX_UI_BLOCKS = 6
MAX_UI_NODES = 300
MAX_UI_DEPTH = 12
MAX_UI_BYTES = 32768
MAX_UI_REPLY_BYTES = 98304
MAX_UI_CHART_POINTS = 500


class UiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class UiValue(UiModel):
    kind: Literal["literal", "state", "expression", "index"] = "literal"
    value: UiScalar = 0


class UiState(UiModel):
    id: UiId
    initial: UiScalar = False


class UiExpression(UiModel):
    id: UiId
    op: Literal[
        "add",
        "sub",
        "mul",
        "div",
        "pow",
        "min",
        "max",
        "round",
        "abs",
        "eq",
        "lt",
        "lte",
        "and",
        "or",
        "not",
        "if",
        "series",
        "sum",
        "payment",
    ]
    args: list[UiValue] = Field(min_length=1, max_length=8)


class UiAction(UiModel):
    type: Literal["set", "reset", "compose"]
    state_id: UiId | None = None
    value: UiValue | None = None
    text: str = Field(default="", max_length=4000)
    include_state: list[UiId] = Field(default_factory=list, max_length=30)


class NodeBase(UiModel):
    id: UiId
    visible_when: UiId | None = None


class TextNode(NodeBase):
    type: Literal["text", "heading", "markdown"]
    text: str = Field(default="", max_length=4000)
    binding: UiId | None = None
    level: int = Field(default=3, ge=2, le=6)


class LayoutNode(NodeBase):
    type: Literal["row", "column", "grid", "card", "tabs", "steps", "timeline"]
    children: list[UiId] = Field(default_factory=list, max_length=100)
    title: str = Field(default="", max_length=200)
    labels: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=100)
    columns: int = Field(default=2, ge=1, le=4)


class TableNode(NodeBase):
    type: Literal["table"]
    columns: list[Annotated[str, Field(max_length=200)]] = Field(min_length=1, max_length=20)
    rows: list[Annotated[list[UiScalar], Field(max_length=20)]] = Field(default_factory=list, max_length=200)
    caption: str = Field(default="", max_length=500)


class ChartSeries(UiModel):
    label: str = Field(max_length=200)
    values: list[float] = Field(default_factory=list, max_length=500)
    binding: UiId | None = None


class ChartNode(NodeBase):
    type: Literal["chart"]
    kind: Literal["line", "bar", "pie"] = "line"
    title: str = Field(default="", max_length=200)
    labels: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=500)
    series: list[ChartSeries] = Field(min_length=1, max_length=8)


class InputNode(NodeBase):
    type: Literal["input", "textarea", "checkbox", "select", "slider"]
    label: str = Field(min_length=1, max_length=200)
    state_id: UiId
    input_type: Literal["text", "number"] = "text"
    options: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=100)
    minimum: float = -1000000000000
    maximum: float = 1000000000000
    step: float = Field(default=1, gt=0)


class ButtonNode(NodeBase):
    type: Literal["button"]
    label: str = Field(min_length=1, max_length=200)
    action: UiAction


class ChoiceNode(NodeBase):
    type: Literal["choice"]
    buttons: InteractiveButtonsV1


class ImageNode(NodeBase):
    type: Literal["image"]
    ref: int = Field(ge=1, le=5)
    alt: str = Field(min_length=1, max_length=500)


class DividerNode(NodeBase):
    type: Literal["divider"]


class DiagramItem(UiModel):
    id: UiId
    label: str = Field(min_length=1, max_length=200)


class DiagramEdge(UiModel):
    source: UiId
    target: UiId
    label: str = Field(default="", max_length=200)


class DiagramNode(NodeBase):
    type: Literal["diagram"]
    title: str = Field(default="", max_length=200)
    items: list[DiagramItem] = Field(min_length=1, max_length=40)
    edges: list[DiagramEdge] = Field(default_factory=list, max_length=80)


UiNode = TextNode | LayoutNode | TableNode | ChartNode | InputNode | ButtonNode | ChoiceNode | ImageNode | DividerNode | DiagramNode


class UiSource(UiModel):
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=200)

    @field_validator("url")
    @classmethod
    def validate_url(cls, url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None:
            raise ValueError("Invalid citation URL")
        if any(character.isspace() or ord(character) < 32 for character in url):
            raise ValueError("Invalid citation URL")
        return url


class StructuredUiV1(UiModel):
    version: Literal[1]
    id: UiId
    fallback_text: str = Field(min_length=1, max_length=4000)
    root_id: UiId
    nodes: list[UiNode] = Field(min_length=1, max_length=MAX_UI_NODES)
    state: list[UiState] = Field(default_factory=list, max_length=100)
    expressions: list[UiExpression] = Field(default_factory=list, max_length=256)
    images: list[GenerativeUiImageV1] = Field(default_factory=list, max_length=5)
    sources: list[UiSource] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_references(self) -> StructuredUiV1:
        nodes = {node.id: node for node in self.nodes}
        states = {item.id: item for item in self.state}
        expressions = {item.id: item for item in self.expressions}
        if len(nodes) != len(self.nodes) or len(states) != len(self.state) or len(expressions) != len(self.expressions):
            raise ValueError("Duplicate UI identifier")
        if self.root_id not in nodes:
            raise ValueError("Missing root")
        visited: set[str] = set()

        def visit(node_id: str, path: set[str]) -> None:
            if node_id not in nodes or node_id in path or len(path) >= MAX_UI_DEPTH:
                raise ValueError("Invalid UI tree")
            if node_id in visited:
                raise ValueError("UI nodes must have one parent")
            visited.add(node_id)
            node = nodes[node_id]
            if isinstance(node, LayoutNode):
                if node.type in {"tabs", "steps", "timeline"} and len(node.labels) != len(node.children):
                    raise ValueError("Missing child labels")
                for child in node.children:
                    visit(child, path | {node_id})

        visit(self.root_id, set())
        if len(visited) != len(nodes):
            raise ValueError("Unreachable UI node")
        for expression in self.expressions:
            count = len(expression.args)
            expected = {
                "sub": 2,
                "div": 2,
                "pow": 2,
                "eq": 2,
                "lt": 2,
                "lte": 2,
                "not": 1,
                "if": 3,
                "payment": 3,
                "series": 2,
                "sum": 1,
                "round": 1,
                "abs": 1,
            }.get(expression.op)
            if expected is not None and count != expected:
                raise ValueError("Invalid expression argument count")
            if expression.op == "series":
                if expression.args[1].kind != "expression":
                    raise ValueError("Series body must reference an expression")
                amount = expression.args[0]
                if amount.kind != "literal" or type(amount.value) is not int or not 0 <= amount.value <= MAX_UI_CHART_POINTS:
                    raise ValueError("Invalid series length")
            for arg in expression.args:
                if arg.kind == "state" and arg.value not in states:
                    raise ValueError("Missing state reference")
                if arg.kind == "expression" and arg.value not in expressions:
                    raise ValueError("Missing expression reference")
        expression_depths: dict[str, int] = {}

        def expression_depth(key: str, path: set[str]) -> int:
            if key in path:
                raise ValueError("Cyclic expression")
            if key in expression_depths:
                return expression_depths[key]
            child_depths = [expression_depth(str(arg.value), path | {key}) for arg in expressions[key].args if arg.kind == "expression"]
            depth = 1 + max(child_depths, default=0)
            if depth > 32:
                raise ValueError("Over-deep expression")
            expression_depths[key] = depth
            return depth

        for key in expressions:
            expression_depth(key, set())
        for node in self.nodes:
            for ref in [node.visible_when, getattr(node, "binding", None)]:
                if ref is not None and ref not in expressions:
                    raise ValueError("Missing display expression")
            if isinstance(node, InputNode):
                if node.state_id not in states or node.minimum > node.maximum:
                    raise ValueError("Invalid input state or range")
                value = states[node.state_id].initial
                if node.input_type == "number" and node.type not in {"input", "slider"}:
                    raise ValueError("Number input type requires an input or slider")
                if (node.type == "textarea" or (node.type == "input" and node.input_type == "text")) and not isinstance(value, str):
                    raise ValueError("Text input requires a string")
                if node.type == "checkbox" and type(value) is not bool:
                    raise ValueError("Checkbox requires boolean")
                if node.type == "select" and (not node.options or value not in node.options):
                    raise ValueError("Select requires a listed option")
                if (node.type == "slider" or node.input_type == "number") and (
                    not isinstance(value, (int, float)) or isinstance(value, bool) or not node.minimum <= value <= node.maximum
                ):
                    raise ValueError("Numeric input requires an in-range number")
            if isinstance(node, ButtonNode):
                action = node.action
                if action.type == "reset" and action.state_id is not None and action.state_id not in states:
                    raise ValueError("Invalid reset state")
                if action.type == "set" and (action.state_id not in states or action.value is None):
                    raise ValueError("Invalid set action")
                if any(ref not in states for ref in action.include_state):
                    raise ValueError("Invalid compose state")
                if action.value:
                    if action.value.kind == "state" and action.value.value not in states:
                        raise ValueError("Invalid action state")
                    if action.value.kind == "expression" and action.value.value not in expressions:
                        raise ValueError("Invalid action expression")
            if isinstance(node, ChartNode) and any(
                series.binding is not None and series.binding not in expressions for series in node.series
            ):
                raise ValueError("Invalid chart binding")
            if isinstance(node, TableNode) and any(len(row) != len(node.columns) for row in node.rows):
                raise ValueError("Invalid table row")
            if isinstance(node, DiagramNode):
                ids = {item.id for item in node.items}
                if len(ids) != len(node.items) or any(edge.source not in ids or edge.target not in ids for edge in node.edges):
                    raise ValueError("Invalid diagram reference")
        if declared_chart_points(self.model_dump()) > MAX_UI_CHART_POINTS:
            raise ValueError("Too many chart points")
        if len(json.dumps(self.model_dump(), ensure_ascii=False, separators=(",", ":")).encode()) > MAX_UI_BYTES:
            raise ValueError("UI block too large")
        return self


def declared_chart_points(ui: dict[str, Any]) -> int:
    """Upper bound for chart data in a document whose references and expressions already validate."""
    expressions = {item["id"]: item for item in ui.get("expressions", [])}
    counts: dict[str, int] = {}

    def expression_points(expression_id: str) -> int:
        if expression_id in counts:
            return counts[expression_id]
        expression = expressions[expression_id]
        if expression["op"] == "series":
            count = int(expression["args"][0]["value"])
        elif expression["op"] == "sum":
            count = 1
        else:
            count = max(
                (expression_points(arg["value"]) if arg["kind"] == "expression" else 1 for arg in expression["args"]),
                default=1,
            )
        counts[expression_id] = count
        return count

    return sum(
        max(len(series["values"]), expression_points(series["binding"]) if series.get("binding") else 0)
        for node in ui["nodes"]
        if node["type"] == "chart"
        for series in node["series"]
    )


class UiMetricsRecord(UiModel):
    """Untrusted client observations: no input content and no authority to read a block."""

    block_id: UiId
    render_ms: float = Field(ge=0, le=3600000)
    action_count: int = Field(ge=0, le=1000000, strict=True)
    action_error_count: int = Field(ge=0, le=1000000, strict=True)
    compose_count: int = Field(ge=0, le=1000000, strict=True)
