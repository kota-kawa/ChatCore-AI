import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import { getStructuredUiDeclaredChartPointCount, getStructuredUiRuntime, parseStructuredUiV1 } from "../lib/chat_page/structured_ui_contract";
import { StructuredUiExpressionEvaluator } from "../lib/chat_page/structured_ui_expressions";
import { prepareStructuredUiChartSeries } from "../components/chat_page/structured_ui_chart";
import {
  ackStructuredUiMetrics,
  activateStructuredUiMetricsScope,
  clearStructuredUiMetrics,
  readStructuredUiMetrics,
  recordStructuredUiMetric,
  structuredUiMetricsScopeFromStateScope,
} from "../lib/chat_page/structured_ui_metrics";

function uiWithExpressions(expressions: unknown[], binding = "series") {
  return parseStructuredUiV1({
    version: 1,
    id: "calc",
    fallback_text: "Calculation unavailable",
    root_id: "root",
    nodes: [{ id: "root", type: "text", text: "Result", binding }],
    state: [{ id: "rate", initial: 0 }],
    expressions,
  });
}

describe("structured UI contract and expressions", () => {
  it("checks graph references, byte size, chart points, and signed image paths", () => {
    const missingExpression = uiWithExpressions([
      { id: "series", op: "add", args: [{ kind: "expression", value: "missing" }] },
    ]);
    assert.equal(missingExpression, null);

    const chartUi = parseStructuredUiV1({
      version: 1,
      id: "chart",
      fallback_text: "Chart unavailable",
      root_id: "root",
      nodes: [
        {
          id: "root",
          type: "chart",
          kind: "line",
          series: [
            { label: "A", values: Array.from({ length: 300 }, () => 1) },
            { label: "B", values: Array.from({ length: 201 }, () => 2) },
          ],
        },
      ],
    });
    assert.equal(chartUi, null);

    const externalImage = parseStructuredUiV1({
      version: 1,
      id: "image",
      fallback_text: "Image unavailable",
      root_id: "root",
      nodes: [{ id: "root", type: "image", ref: 1, alt: "Example" }],
      images: [{ ref: 1, url: "https://example.test/image.png", source_url: "https://example.test", source_title: "Example" }],
    });
    assert.equal(externalImage, null);

    const children = Array.from({ length: 4 }, (_, index) => `item${index}`);
    const oversizedUtf8 = parseStructuredUiV1({
      version: 1,
      id: "large",
      fallback_text: "Too large",
      root_id: "root",
      nodes: [
        { id: "root", type: "column", children },
        ...children.map((id) => ({ id, type: "text", text: "界".repeat(3000) })),
      ],
    });
    assert.equal(oversizedUtf8, null);
  });

  it("requires string defaults for text controls and limits number input types to numeric controls", () => {
    const document = (node: Record<string, unknown>, initial: unknown) => parseStructuredUiV1({
      version: 1,
      id: "form",
      fallback_text: "Form unavailable",
      root_id: "root",
      nodes: [{ id: "root", ...node }],
      state: [{ id: "value", initial }],
    });

    assert.notEqual(document({ type: "input", label: "Text", state_id: "value" }, "hello"), null);
    assert.notEqual(document({ type: "textarea", label: "Notes", state_id: "value" }, ""), null);
    assert.equal(document({ type: "input", label: "Text", state_id: "value" }, 7), null);
    assert.equal(document({ type: "textarea", label: "Notes", state_id: "value" }, 7), null);
    assert.equal(document({ type: "textarea", label: "Notes", state_id: "value", input_type: "number" }, 7), null);
    assert.notEqual(document({ type: "slider", label: "Amount", state_id: "value", input_type: "number" }, 7), null);
  });

  it("uses declared expression lengths and the larger static or bound series length", () => {
    const chartUi = parseStructuredUiV1({
      version: 1,
      id: "chart_budget",
      fallback_text: "Chart unavailable",
      root_id: "root",
      nodes: [{
        id: "root",
        type: "chart",
        kind: "line",
        series: [
          { label: "Largest", values: Array.from({ length: 200 }, () => 1), binding: "combined" },
          { label: "Static wins", values: Array.from({ length: 100 }, () => 1), binding: "scalar" },
          { label: "Static", values: Array.from({ length: 99 }, () => 1) },
          { label: "Scalar", binding: "scalar" },
        ],
      }],
      expressions: [
        { id: "point", op: "round", args: [{ kind: "index", value: 0 }] },
        { id: "large", op: "series", args: [{ kind: "literal", value: 300 }, { kind: "expression", value: "point" }] },
        { id: "small", op: "series", args: [{ kind: "literal", value: 200 }, { kind: "expression", value: "point" }] },
        { id: "combined", op: "add", args: [{ kind: "expression", value: "large" }, { kind: "expression", value: "small" }] },
        { id: "scalar", op: "sum", args: [{ kind: "expression", value: "large" }] },
      ],
    });
    assert.notEqual(chartUi, null);
    assert.equal(getStructuredUiDeclaredChartPointCount(getStructuredUiRuntime(chartUi!)), 500);

    const overBudget = parseStructuredUiV1({
      ...chartUi,
      nodes: [{
        id: "root",
        type: "chart",
        kind: "line",
        series: [
          { label: "Largest", values: Array.from({ length: 200 }, () => 1), binding: "combined" },
          { label: "Static wins", values: Array.from({ length: 100 }, () => 1), binding: "scalar" },
          { label: "Static", values: Array.from({ length: 99 }, () => 1) },
          { label: "Scalar", binding: "scalar" },
          { label: "Extra", values: [1] },
        ],
      }],
    });
    assert.equal(overBudget, null);
  });

  it("requires series point counts to be literal integers within the chart limit", () => {
    const chart = (count: unknown) => parseStructuredUiV1({
      version: 1,
      id: "chart_count",
      fallback_text: "Chart unavailable",
      root_id: "root",
      nodes: [{ id: "root", type: "chart", kind: "line", series: [{ label: "A", binding: "points" }] }],
      state: [{ id: "size", initial: 4 }],
      expressions: [
        { id: "point", op: "round", args: [{ kind: "index", value: 0 }] },
        { id: "points", op: "series", args: [count, { kind: "expression", value: "point" }] },
      ],
    });

    assert.notEqual(chart({ kind: "literal", value: 0 }), null);
    assert.equal(chart({ kind: "literal", value: 1.5 }), null);
    assert.equal(chart({ kind: "literal", value: 501 }), null);
    assert.equal(chart({ kind: "state", value: "size" }), null);
  });

  it("evaluates bounded payment scalars and vectors for variable charts", () => {
    const ui = parseStructuredUiV1({
      version: 1,
      id: "payment_chart",
      fallback_text: "Payment chart unavailable",
      root_id: "root",
      nodes: [{ id: "root", type: "chart", kind: "line", series: [{ label: "Payment", binding: "variable_payment" }] }],
      state: [{ id: "principal", initial: 1200 }, { id: "rate", initial: 0.01 }],
      expressions: [
        { id: "zero_rate_payment", op: "payment", args: [
          { kind: "literal", value: 1200 }, { kind: "literal", value: 0 }, { kind: "literal", value: 12 },
        ] },
        { id: "fixed_payment", op: "payment", args: [
          { kind: "literal", value: 1200 }, { kind: "literal", value: 0.01 }, { kind: "literal", value: 12 },
        ] },
        { id: "negative_principal", op: "payment", args: [
          { kind: "literal", value: -1 }, { kind: "literal", value: 0.01 }, { kind: "literal", value: 12 },
        ] },
        { id: "zero_periods", op: "payment", args: [
          { kind: "literal", value: 1200 }, { kind: "literal", value: 0.01 }, { kind: "literal", value: 0 },
        ] },
        { id: "period_index", op: "add", args: [{ kind: "index", value: 1 }, { kind: "literal", value: 0 }] },
        { id: "periods", op: "series", args: [{ kind: "literal", value: 3 }, { kind: "expression", value: "period_index" }] },
        { id: "variable_payment", op: "payment", args: [
          { kind: "state", value: "principal" }, { kind: "state", value: "rate" }, { kind: "expression", value: "periods" },
        ] },
      ],
    });
    assert.notEqual(ui, null);
    const runtime = getStructuredUiRuntime(ui!);
    const evaluator = new StructuredUiExpressionEvaluator(runtime, { principal: 1200, rate: 0.01 });

    assert.equal(evaluator.evaluate("zero_rate_payment"), 100);
    const fixed = 1200 * 0.01 / -Math.expm1(-12 * Math.log1p(0.01));
    assert.ok(Math.abs((evaluator.evaluate("fixed_payment") as number) - fixed) < 1e-12);
    assert.equal(evaluator.evaluate("negative_principal"), undefined);
    assert.equal(evaluator.evaluate("zero_periods"), undefined);

    const chart = runtime.nodes[0];
    if (!chart || chart.type !== "chart") throw new Error("Payment chart fixture is invalid");
    const series = prepareStructuredUiChartSeries(chart, evaluator, { remaining: 500 });
    assert.equal(series[0]?.values.length, 3);
    for (const [index, value] of series[0]!.values.entries()) {
      const expected = 1200 * 0.01 / -Math.expm1(-(index + 1) * Math.log1p(0.01));
      assert.ok(Math.abs(value - expected) < 1e-12);
    }
  });

  it("keeps only safe HTTP(S) source links", () => {
    const ui = parseStructuredUiV1({
      version: 1,
      id: "source_list",
      fallback_text: "Unavailable",
      root_id: "root",
      nodes: [{ id: "root", type: "text", text: "See [1]." }],
      sources: [
        { url: "https://example.test/path", title: "Reference" },
        { url: "javascript:alert(1)", title: "Unsafe scheme" },
        { url: "https://user:pass@example.test/", title: "Credentials" },
        { url: "https://example.test/with space", title: "Whitespace" },
      ],
    });

    assert.deepEqual(ui?.sources, [{ url: "https://example.test/path", title: "Reference" }]);
  });

  it("evaluates safe arithmetic, lazy conditions, and indexed series", () => {
    const ui = uiWithExpressions([
      { id: "unsafe", op: "div", args: [{ kind: "literal", value: 12 }, { kind: "state", value: "rate" }] },
      { id: "is_zero", op: "eq", args: [{ kind: "state", value: "rate" }, { kind: "literal", value: 0 }] },
      { id: "safe_if", op: "if", args: [{ kind: "expression", value: "is_zero" }, { kind: "literal", value: 0 }, { kind: "expression", value: "unsafe" }] },
      { id: "short_and", op: "and", args: [{ kind: "literal", value: false }, { kind: "expression", value: "unsafe" }] },
      { id: "short_or", op: "or", args: [{ kind: "literal", value: true }, { kind: "expression", value: "unsafe" }] },
      { id: "index_value", op: "round", args: [{ kind: "index", value: 0 }] },
      { id: "series", op: "series", args: [{ kind: "literal", value: 3 }, { kind: "expression", value: "index_value" }] },
      { id: "sum", op: "sum", args: [{ kind: "expression", value: "series" }] },
      { id: "difference", op: "sub", args: [{ kind: "literal", value: 10 }, { kind: "literal", value: 2 }] },
    ]);
    assert.notEqual(ui, null);
    const evaluator = new StructuredUiExpressionEvaluator(getStructuredUiRuntime(ui!), { rate: 0 });

    assert.equal(evaluator.evaluate("safe_if"), 0);
    assert.equal(evaluator.evaluate("short_and"), false);
    assert.equal(evaluator.evaluate("short_or"), true);
    assert.deepEqual(evaluator.evaluate("series"), [0, 1, 2]);
    assert.equal(evaluator.evaluate("sum"), 3);
    assert.equal(evaluator.evaluate("difference"), 8);
    assert.equal(evaluator.isExhausted, false);
  });

  it("caps expression work at ten thousand evaluation steps", () => {
    const chain: Array<Record<string, unknown>> = [
      { id: "step0", op: "add", args: [{ kind: "index", value: 0 }, { kind: "literal", value: 1 }] },
    ];
    for (let index = 1; index < 30; index += 1) {
      chain.push({ id: `step${index}`, op: "add", args: [{ kind: "expression", value: `step${index - 1}` }, { kind: "literal", value: 1 }] });
    }
    chain.push({ id: "series", op: "series", args: [{ kind: "literal", value: 500 }, { kind: "expression", value: "step29" }] });
    const ui = uiWithExpressions(chain);
    assert.notEqual(ui, null);
    const evaluator = new StructuredUiExpressionEvaluator(getStructuredUiRuntime(ui!), {});

    assert.equal(evaluator.evaluate("series"), undefined);
    assert.equal(evaluator.isExhausted, true);
  });
});

describe("structured UI metric buffering", () => {
  beforeEach(() => clearStructuredUiMetrics());

  it("derives a user-room scope and keeps snapshots until acknowledged", () => {
    const scope = structuredUiMetricsScopeFromStateScope(`${encodeURIComponent("user:7")}:room%3A2:answer:form`);
    assert.equal(scope, `${encodeURIComponent("user:7")}:room%3A2`);
    assert.equal(structuredUiMetricsScopeFromStateScope("guest:room:answer:form"), null);

    recordStructuredUiMetric(scope!, "form", { render_ms: 12, action_count: 1, compose_count: 1 });
    const first = readStructuredUiMetrics(scope!);
    assert.deepEqual(first?.metrics, [{ block_id: "form", render_ms: 12, action_count: 1, action_error_count: 0, compose_count: 1 }]);

    recordStructuredUiMetric(scope!, "form", { action_count: 1, action_error_count: 1 });
    assert.equal(readStructuredUiMetrics(scope!)?.snapshotId, first?.snapshotId);
    ackStructuredUiMetrics(scope!, first!.snapshotId);
    const second = readStructuredUiMetrics(scope!);
    assert.deepEqual(second?.metrics, [{ block_id: "form", render_ms: 0, action_count: 1, action_error_count: 1, compose_count: 0 }]);
    ackStructuredUiMetrics(scope!, second!.snapshotId);
    assert.equal(readStructuredUiMetrics(scope!), null);
  });

  it("clears the old room buffer when the active scope changes", () => {
    const oldScope = "user%3A7:room-a";
    const newScope = "user%3A7:room-b";
    activateStructuredUiMetricsScope(oldScope);
    recordStructuredUiMetric(oldScope, "form", { action_count: 1 });
    activateStructuredUiMetricsScope(newScope);

    assert.equal(readStructuredUiMetrics(oldScope), null);
  });
});
