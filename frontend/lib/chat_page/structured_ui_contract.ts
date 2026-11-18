// Validates the structured UI payload at the browser boundary. The generated Zod
// schema owns field shapes; these checks mirror the backend's cross-reference rules.
import { StructuredUiV1Schema, type StructuredUiV1 } from "../../types/generated/api_schemas";

export type StructuredUiScalar = string | number | boolean;
export type StructuredUiSource = { url: string; title: string };
export type StructuredUiValue = {
  kind: "literal" | "state" | "expression" | "index";
  value: StructuredUiScalar;
};

export type StructuredUiState = { id: string; initial: StructuredUiScalar };
export type StructuredUiExpression = { id: string; op: string; args: StructuredUiValue[] };
export type StructuredUiImage = { ref: number; url: string; source_url: string; source_title: string };

export type StructuredUiTextNode = {
  id: string;
  type: "text" | "heading" | "markdown";
  text: string;
  binding: string | null;
  level: number;
  visible_when: string | null;
};
export type StructuredUiLayoutNode = {
  id: string;
  type: "row" | "column" | "grid" | "card" | "tabs" | "steps" | "timeline";
  children: string[];
  title: string;
  labels: string[];
  columns: number;
  visible_when: string | null;
};
export type StructuredUiTableNode = {
  id: string;
  type: "table";
  columns: string[];
  rows: StructuredUiScalar[][];
  caption: string;
  visible_when: string | null;
};
export type StructuredUiChartNode = {
  id: string;
  type: "chart";
  kind: "line" | "bar" | "pie";
  title: string;
  labels: string[];
  series: Array<{ label: string; values: number[]; binding: string | null }>;
  visible_when: string | null;
};
export type StructuredUiInputNode = {
  id: string;
  type: "input" | "textarea" | "checkbox" | "select" | "slider";
  label: string;
  state_id: string;
  input_type: "text" | "number";
  options: string[];
  minimum: number;
  maximum: number;
  step: number;
  visible_when: string | null;
};
export type StructuredUiButtonNode = {
  id: string;
  type: "button";
  label: string;
  action: {
    type: "set" | "reset" | "compose";
    state_id: string | null;
    value: StructuredUiValue | null;
    text: string;
    include_state: string[];
  };
  visible_when: string | null;
};
export type StructuredUiChoiceNode = {
  id: string;
  type: "choice";
  buttons: { type: "yes_no" | "multiple_choice" | "multiple_select"; question: string; options?: string[] | null };
  visible_when: string | null;
};
export type StructuredUiImageNode = {
  id: string;
  type: "image";
  ref: number;
  alt: string;
  visible_when: string | null;
};
export type StructuredUiDividerNode = { id: string; type: "divider"; visible_when: string | null };
export type StructuredUiDiagramNode = {
  id: string;
  type: "diagram";
  title: string;
  items: Array<{ id: string; label: string }>;
  edges: Array<{ source: string; target: string; label: string }>;
  visible_when: string | null;
};
export type StructuredUiNode =
  | StructuredUiTextNode
  | StructuredUiLayoutNode
  | StructuredUiTableNode
  | StructuredUiChartNode
  | StructuredUiInputNode
  | StructuredUiButtonNode
  | StructuredUiChoiceNode
  | StructuredUiImageNode
  | StructuredUiDividerNode
  | StructuredUiDiagramNode;

export type StructuredUiRuntime = Omit<StructuredUiV1, "nodes" | "state" | "expressions" | "images" | "sources"> & {
  nodes: StructuredUiNode[];
  state: StructuredUiState[];
  expressions: StructuredUiExpression[];
  images: StructuredUiImage[];
  sources?: StructuredUiSource[];
};

const ID_PATTERN = /^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/;
const MAX_UI_NODES = 300;
const MAX_UI_DEPTH = 12;
const MAX_EXPRESSION_DEPTH = 32;
const MAX_CHART_POINTS = 500;
const MAX_STRUCTURED_UI_SOURCES = 10;
const MAX_UI_BYTES = 32_768;
const SIGNED_IMAGE_PATH = /^\/api\/chat\/web-images\/[0-9a-f]{32}\/[A-Za-z0-9_-]{1,4000}$/;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNumericScalar(value: StructuredUiScalar): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isHttpUrl(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 1000) return false;
  try {
    const url = new URL(value);
    return (url.protocol === "http:" || url.protocol === "https:") && Boolean(url.host) && !url.username && !url.password;
  } catch {
    return false;
  }
}

function normalizeSourceUrl(value: unknown): string | null {
  if (typeof value !== "string" || Array.from(value).length > 2000 || /\s/.test(value)) return null;
  try {
    const url = new URL(value);
    if ((url.protocol !== "http:" && url.protocol !== "https:") || !url.hostname || url.username || url.password) return null;
    return url.toString();
  } catch {
    return null;
  }
}

function normalizeStructuredUiSources(value: unknown): StructuredUiSource[] | null {
  if (!Array.isArray(value) || value.length > MAX_STRUCTURED_UI_SOURCES) return null;
  return value.flatMap((rawSource) => {
    if (!rawSource || typeof rawSource !== "object" || Array.isArray(rawSource)) return [];
    const source = rawSource as Record<string, unknown>;
    const url = normalizeSourceUrl(source.url);
    const title = typeof source.title === "string" ? source.title.trim() : "";
    if (!url || Array.from(title).length < 1 || Array.from(title).length > 200) return [];
    return [{ url, title }];
  });
}

function declaredExpressionPointCount(
  expressionId: string,
  expressions: Map<string, StructuredUiExpression>,
  active: Set<string>,
  cached: Map<string, number>,
): number | null {
  const previous = cached.get(expressionId);
  if (previous !== undefined) return previous;
  if (active.has(expressionId)) return null;
  const expression = expressions.get(expressionId);
  if (!expression) return null;
  active.add(expressionId);

  let count: number | null;
  if (expression.op === "series") {
    const amount = expression.args[0];
    count = amount?.kind === "literal"
      && typeof amount.value === "number"
      && Number.isInteger(amount.value)
      && amount.value >= 0
      && amount.value <= MAX_CHART_POINTS
      ? amount.value
      : null;
  } else if (expression.op === "sum") {
    count = 1;
  } else {
    const childCounts = expression.args.map((argument) => argument.kind === "expression"
      ? declaredExpressionPointCount(String(argument.value), expressions, active, cached)
      : 1);
    count = childCounts.some((childCount) => childCount === null)
      ? null
      : Math.max(...childCounts as number[]);
  }

  active.delete(expressionId);
  if (count !== null) cached.set(expressionId, count);
  return count;
}

/** Declared chart points include both static values and the bounded output declared by each binding. */
export function getStructuredUiDeclaredChartPointCount(ui: StructuredUiRuntime): number | null {
  const expressions = new Map(ui.expressions.map((expression) => [expression.id, expression]));
  const cached = new Map<string, number>();
  let total = 0;
  for (const node of ui.nodes) {
    if (node.type !== "chart") continue;
    for (const series of node.series) {
      const bindingCount = series.binding === null
        ? 0
        : declaredExpressionPointCount(series.binding, expressions, new Set(), cached);
      if (bindingCount === null) return null;
      total += Math.max(series.values.length, bindingCount);
      if (total > MAX_CHART_POINTS) return total;
    }
  }
  return total;
}

function hasValidExpressionArity(expression: StructuredUiExpression): boolean {
  const count = expression.args.length;
  switch (expression.op) {
    case "abs":
    case "not":
    case "round":
      return count === 1;
    case "sub":
    case "div":
    case "pow":
    case "eq":
    case "lt":
    case "lte":
      return count === 2;
    case "payment":
      return count === 3;
    case "if":
      return count === 3;
    case "series":
      return count === 2 && expression.args[0]?.kind === "literal" && expression.args[1]?.kind === "expression";
    case "sum":
      return count === 1;
    case "add":
    case "mul":
    case "min":
    case "max":
    case "and":
    case "or":
      return count >= 1;
    default:
      return false;
  }
}

function validateReferences(ui: StructuredUiRuntime): boolean {
  if (ui.nodes.length < 1 || ui.nodes.length > MAX_UI_NODES) return false;
  const nodes = new Map<string, StructuredUiNode>();
  const states = new Map<string, StructuredUiState>();
  const expressions = new Map<string, StructuredUiExpression>();

  for (const node of ui.nodes) {
    if (!node || !ID_PATTERN.test(node.id) || nodes.has(node.id)) return false;
    nodes.set(node.id, node);
  }
  for (const state of ui.state) {
    if (!state || !ID_PATTERN.test(state.id) || states.has(state.id)) return false;
    if (typeof state.initial === "number" && !Number.isFinite(state.initial)) return false;
    states.set(state.id, state);
  }
  for (const expression of ui.expressions) {
    if (!expression || !ID_PATTERN.test(expression.id) || expressions.has(expression.id)) return false;
    if (!hasValidExpressionArity(expression)) return false;
    expressions.set(expression.id, expression);
  }

  if (!ID_PATTERN.test(ui.root_id) || !nodes.has(ui.root_id)) return false;
  const visited = new Set<string>();
  const visitNode = (id: string, path: Set<string>): boolean => {
    const node = nodes.get(id);
    if (!node || path.has(id) || path.size >= MAX_UI_DEPTH || visited.has(id)) return false;
    visited.add(id);
    if (node.visible_when !== null && !expressions.has(node.visible_when)) return false;
    if ((node.type === "text" || node.type === "heading" || node.type === "markdown") && node.binding !== null && !expressions.has(node.binding)) {
      return false;
    }
    if (node.type === "chart") {
      for (const series of node.series) {
        if (series.values.some((value) => !Number.isFinite(value))) return false;
        if (series.binding !== null && !expressions.has(series.binding)) return false;
      }
    }
    if (node.type === "input" || node.type === "textarea" || node.type === "checkbox" || node.type === "select" || node.type === "slider") {
      const state = states.get(node.state_id);
      if (!state || node.minimum > node.maximum || !isFiniteNumber(node.minimum) || !isFiniteNumber(node.maximum) || !isFiniteNumber(node.step) || node.step <= 0) {
        return false;
      }
      if (node.type === "checkbox" && typeof state.initial !== "boolean") return false;
      if (node.type === "select" && (!node.options.length || typeof state.initial !== "string" || !node.options.includes(state.initial))) return false;
      if (node.input_type === "number" && node.type !== "input" && node.type !== "slider") return false;
      if ((node.type === "textarea" || (node.type === "input" && node.input_type === "text")) && typeof state.initial !== "string") return false;
      if ((node.type === "slider" || node.input_type === "number") && (!isNumericScalar(state.initial) || state.initial < node.minimum || state.initial > node.maximum)) {
        return false;
      }
    }
    if (node.type === "button") {
      const action = node.action;
      if (action.type === "set" && (!action.state_id || !states.has(action.state_id) || !action.value)) return false;
      if (action.type === "reset" && action.state_id !== null && !states.has(action.state_id)) return false;
      if ((action.include_state ?? []).some((stateId) => !states.has(stateId))) return false;
      if (action.value?.kind === "state" && !states.has(String(action.value.value))) return false;
      if (action.value?.kind === "expression" && !expressions.has(String(action.value.value))) return false;
      if (typeof action.value?.value === "number" && !Number.isFinite(action.value.value)) return false;
    }
    if (node.type === "table" && node.rows.some((row) => row.length !== node.columns.length)) return false;
    if (node.type === "diagram") {
      const itemIds = new Set(node.items.map((item) => item.id));
      if (itemIds.size !== node.items.length || node.edges.some((edge) => !itemIds.has(edge.source) || !itemIds.has(edge.target))) return false;
    }
    if (node.type === "row" || node.type === "column" || node.type === "grid" || node.type === "card" || node.type === "tabs" || node.type === "steps" || node.type === "timeline") {
      if ((node.type === "tabs" || node.type === "steps" || node.type === "timeline") && node.labels.length !== node.children.length) return false;
      for (const childId of node.children) {
        if (!visitNode(childId, new Set([...path, id]))) return false;
      }
    }
    return true;
  };
  if (!visitNode(ui.root_id, new Set()) || visited.size !== nodes.size) return false;

  for (const expression of ui.expressions) {
    for (const value of expression.args) {
      if (value.kind === "state" && !states.has(String(value.value))) return false;
      if (value.kind === "expression" && !expressions.has(String(value.value))) return false;
      if (value.kind === "index" && typeof value.value === "string" && !Number.isFinite(Number(value.value))) return false;
      if (typeof value.value === "number" && !Number.isFinite(value.value)) return false;
    }
    if (expression.op === "series") {
      const amount = expression.args[0].value;
      if (typeof amount !== "number" || !Number.isInteger(amount) || amount < 0 || amount > MAX_CHART_POINTS) return false;
    }
  }

  const activeExpressions = new Set<string>();
  const expressionDepths = new Map<string, number>();
  const expressionDepth = (id: string): number | null => {
    if (activeExpressions.has(id)) return null;
    const cached = expressionDepths.get(id);
    if (cached !== undefined) return cached;
    const expression = expressions.get(id);
    if (!expression) return null;
    activeExpressions.add(id);
    let maximumChildDepth = 0;
    for (const value of expression.args) {
      if (value.kind !== "expression") continue;
      const childDepth = expressionDepth(String(value.value));
      if (childDepth === null) return null;
      maximumChildDepth = Math.max(maximumChildDepth, childDepth);
    }
    activeExpressions.delete(id);
    const depth = maximumChildDepth + 1;
    if (depth > MAX_EXPRESSION_DEPTH) return null;
    expressionDepths.set(id, depth);
    return depth;
  };
  for (const id of expressions.keys()) {
    if (expressionDepth(id) === null) return false;
  }

  const declaredChartPoints = getStructuredUiDeclaredChartPointCount(ui);
  if (declaredChartPoints === null || declaredChartPoints > MAX_CHART_POINTS) return false;

  const imageRefs = new Set<number>();
  for (const image of ui.images) {
    if (!Number.isInteger(image.ref) || image.ref < 1 || image.ref > 5 || imageRefs.has(image.ref)) return false;
    if (!SIGNED_IMAGE_PATH.test(image.url) || !isHttpUrl(image.source_url)) return false;
    imageRefs.add(image.ref);
  }
  return true;
}

/** Parse and validate a structured UI block. Invalid blocks return null so callers can fall back to text. */
export function parseStructuredUiV1(value: unknown): StructuredUiV1 | null {
  try {
    const rawJson = JSON.stringify(value);
    if (typeof rawJson !== "string" || new TextEncoder().encode(rawJson).byteLength > MAX_UI_BYTES) return null;
  } catch {
    return null;
  }
  const result = StructuredUiV1Schema.safeParse(value);
  if (!result.success) return null;
  const data = result.data as unknown as StructuredUiRuntime;
  const rawSources = (result.data as unknown as { sources?: unknown }).sources;
  const sources = rawSources === undefined ? undefined : normalizeStructuredUiSources(rawSources);
  if (rawSources !== undefined && sources === null) return null;
  const normalizedSources = sources ?? undefined;
  const candidate: StructuredUiRuntime = {
    ...data,
    ...(normalizedSources !== undefined ? { sources: normalizedSources } : {}),
    nodes: data.nodes.map((node) => {
      if (node.type === "row" || node.type === "column" || node.type === "grid" || node.type === "card" || node.type === "tabs" || node.type === "steps" || node.type === "timeline") {
        return { ...node, children: node.children ?? [], labels: node.labels ?? [] };
      }
      if (node.type === "table") return { ...node, rows: node.rows ?? [] };
      if (node.type === "chart") return { ...node, labels: node.labels ?? [], series: node.series.map((series) => ({ ...series, values: series.values ?? [] })) };
      if (node.type === "input" || node.type === "textarea" || node.type === "checkbox" || node.type === "select" || node.type === "slider") {
        return { ...node, options: node.options ?? [] };
      }
      if (node.type === "button") return { ...node, action: { ...node.action, include_state: node.action.include_state ?? [] } };
      if (node.type === "choice") {
        const question = node.buttons.question.trim();
        if (node.buttons.type === "yes_no") return { ...node, buttons: { ...node.buttons, question, options: null } };
        const options = Array.from(new Set((node.buttons.options ?? []).map((option) => option.trim()).filter(Boolean)));
        return { ...node, buttons: { ...node.buttons, question, options } };
      }
      if (node.type === "diagram") return { ...node, edges: node.edges ?? [] };
      return node;
    }),
    state: data.state ?? [],
    expressions: data.expressions ?? [],
    images: data.images ?? [],
  };
  for (const node of candidate.nodes) {
    if (node.type !== "choice") continue;
    if (!node.buttons.question) return null;
    const optionCount = node.buttons.options?.length ?? 0;
    if (node.buttons.type === "multiple_choice" && optionCount < 1) return null;
    if (node.buttons.type === "multiple_select" && optionCount < 2) return null;
  }
  try {
    const normalizedJson = JSON.stringify(candidate);
    if (new TextEncoder().encode(normalizedJson).byteLength > MAX_UI_BYTES) return null;
  } catch {
    return null;
  }
  if (!validateReferences(candidate)) return null;
  return candidate as unknown as StructuredUiV1;
}

export function getStructuredUiRuntime(ui: StructuredUiV1): StructuredUiRuntime {
  return ui as unknown as StructuredUiRuntime;
}

export const STRUCTURED_UI_MAX_EVALUATION_STEPS = 10_000;
export const STRUCTURED_UI_MAX_CHART_POINTS = MAX_CHART_POINTS;
