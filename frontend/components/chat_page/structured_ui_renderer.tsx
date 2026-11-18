import { Component, createElement, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ErrorInfo, type ReactNode } from "react";

import type { StructuredUiV1 } from "../../types/generated/api_schemas";
import {
  getStructuredUiRuntime,
  parseStructuredUiV1,
  type StructuredUiButtonNode,
  type StructuredUiInputNode,
  type StructuredUiLayoutNode,
  type StructuredUiNode,
  type StructuredUiRuntime,
  type StructuredUiScalar,
  type StructuredUiSource,
} from "../../lib/chat_page/structured_ui_contract";
import { StructuredUiExpressionEvaluator, stateValueForCompose } from "../../lib/chat_page/structured_ui_expressions";
import {
  activateStructuredUiMetricsScope,
  recordStructuredUiMetric,
  structuredUiMetricsScopeFromStateScope,
} from "../../lib/chat_page/structured_ui_metrics";
import { InteractiveButtons } from "./interactive_buttons";
import { prepareStructuredUiChartSeries, StructuredUiChart, type PointBudget } from "./structured_ui_chart";
import { StructuredUiInlineMarkdown, StructuredUiMarkdown } from "./structured_ui_markdown";
import { useTranslation } from "../../contexts/locale_context";

type Props = {
  ui: StructuredUiV1;
  onCompose?: (text: string) => void;
  disabled?: boolean;
  stateScope?: string;
};

type PersistedSelections = { selected: Record<string, StructuredUiScalar>; tabs: Record<string, number> };
type ActiveSteps = Record<string, number>;

const LOCAL_STORAGE_PREFIX = "chatcore.structured-ui:";

function scopeStorageKey(stateScope: string): string {
  return `${LOCAL_STORAGE_PREFIX}${stateScope}`;
}

function defaultStateValues(ui: StructuredUiRuntime): Record<string, StructuredUiScalar> {
  return Object.fromEntries(ui.state.map((item) => [item.id, item.initial]));
}

function readPersistedSelections(ui: StructuredUiRuntime, stateScope: string): PersistedSelections {
  const empty = { selected: {}, tabs: {} };
  if (typeof window === "undefined") return empty;
  try {
    const encoded = window.localStorage.getItem(scopeStorageKey(stateScope));
    if (!encoded) return empty;
    const parsed = JSON.parse(encoded) as { version?: unknown; selected?: unknown; tabs?: unknown };
    if (parsed.version !== 1 || !parsed.selected || typeof parsed.selected !== "object" || !parsed.tabs || typeof parsed.tabs !== "object") return empty;
    const selectedSource = parsed.selected as Record<string, unknown>;
    const tabsSource = parsed.tabs as Record<string, unknown>;
    const states = new Map(ui.state.map((state) => [state.id, state]));
    const controls = ui.nodes.filter((node): node is StructuredUiInputNode =>
      node.type === "input" || node.type === "textarea" || node.type === "checkbox" || node.type === "select" || node.type === "slider",
    );
    const selected: Record<string, StructuredUiScalar> = {};
    for (const control of controls) {
      if (control.type !== "checkbox" && control.type !== "select") continue;
      const value = selectedSource[control.state_id];
      if (control.type === "checkbox" && typeof value === "boolean") selected[control.state_id] = value;
      if (control.type === "select" && typeof value === "string" && control.options.includes(value)) selected[control.state_id] = value;
    }
    const tabs: Record<string, number> = {};
    for (const node of ui.nodes) {
      if (node.type !== "tabs") continue;
      const value = tabsSource[node.id];
      if (typeof value === "number" && Number.isInteger(value) && value >= 0 && value < node.children.length) tabs[node.id] = value;
    }
    for (const [stateId, value] of Object.entries(selected)) {
      if (!states.has(stateId)) delete selected[stateId];
      else if (typeof value === "number" && !Number.isFinite(value)) delete selected[stateId];
    }
    return { selected, tabs };
  } catch {
    return empty;
  }
}

function persistedSelections(ui: StructuredUiRuntime, stateValues: Record<string, StructuredUiScalar>, tabs: Record<string, number>): PersistedSelections {
  const selected: Record<string, StructuredUiScalar> = {};
  for (const node of ui.nodes) {
    if (node.type === "checkbox" && typeof stateValues[node.state_id] === "boolean") selected[node.state_id] = stateValues[node.state_id];
    if (node.type === "select" && typeof stateValues[node.state_id] === "string" && node.options.includes(stateValues[node.state_id] as string)) {
      selected[node.state_id] = stateValues[node.state_id];
    }
  }
  const validTabs: Record<string, number> = {};
  for (const node of ui.nodes) {
    if (node.type !== "tabs") continue;
    const index = tabs[node.id] ?? 0;
    if (Number.isInteger(index) && index >= 0 && index < node.children.length) validTabs[node.id] = index;
  }
  return { selected, tabs: validTabs };
}

function savePersistedSelections(stateScope: string, value: PersistedSelections): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(scopeStorageKey(stateScope), JSON.stringify({ version: 1, ...value }));
  } catch {
    // Storage may be disabled or full; the active UI state remains in React memory.
  }
}

function isFinalizedBlockScope(previous: string, next: string): boolean {
  const previousSegments = previous.split(":");
  const nextSegments = next.split(":");
  return previousSegments.length === 4 && nextSegments.length === 4
    && previousSegments[0] === nextSegments[0]
    && previousSegments[1] === nextSegments[1]
    && previousSegments[2].startsWith("local%3A")
    && /^server%3A[1-9]\d*$/.test(nextSegments[2])
    && previousSegments[3] === nextSegments[3];
}

function scalarText(value: StructuredUiScalar | undefined): string {
  return value === undefined ? "" : typeof value === "boolean" ? (value ? "true" : "false") : String(value);
}

function expressionText(value: StructuredUiScalar | Array<number | boolean> | undefined): string {
  if (Array.isArray(value)) return value.map((item) => String(item)).join(", ");
  return scalarText(value);
}

function stateUpdateIsValid(ui: StructuredUiRuntime, stateId: string, value: StructuredUiScalar): boolean {
  if (typeof value === "number" && !Number.isFinite(value)) return false;
  if (typeof value === "string" && Array.from(value).length > 4000) return false;
  const controls = ui.nodes.filter((node): node is StructuredUiInputNode =>
    (node.type === "input" || node.type === "textarea" || node.type === "checkbox" || node.type === "select" || node.type === "slider") && node.state_id === stateId,
  );
  if (controls.length === 0) return true;
  return controls.every((control) => {
    if (control.type === "checkbox") return typeof value === "boolean";
    if (control.type === "select") return typeof value === "string" && control.options.includes(value);
    if (control.type === "slider" || (control.type === "input" && control.input_type === "number")) {
      return typeof value === "number" && Number.isFinite(value) && value >= control.minimum && value <= control.maximum;
    }
    return typeof value === "string";
  });
}

function parseNumericDraft(value: string, node: StructuredUiInputNode): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < node.minimum || parsed > node.maximum) return null;
  return parsed;
}

function namedHeading(level: number, content: ReactNode) {
  const tag = `h${Math.max(2, Math.min(6, level))}` as "h2" | "h3" | "h4" | "h5" | "h6";
  return createElement(tag, { className: "structured-ui__heading" }, content);
}

function nextIndex(current: number, total: number, direction: -1 | 1): number {
  return Math.min(Math.max(current + direction, 0), Math.max(total - 1, 0));
}

function buildActionComposeText(action: StructuredUiButtonNode["action"], values: Record<string, StructuredUiScalar>): string {
  const stateLines = action.include_state.map((stateId) => `${stateId}: ${stateValueForCompose(values[stateId])}`);
  return [action.text.trim(), ...stateLines].filter(Boolean).join("\n");
}

function chartPointBudget(): PointBudget {
  return { remaining: 500 };
}

function structuredUiDomId(instanceId: string, nodeId: string, suffix = ""): string {
  return `structured-ui-${instanceId}-${nodeId}${suffix ? `-${suffix}` : ""}`;
}

function renderInput(
  instanceId: string,
  node: StructuredUiInputNode,
  value: StructuredUiScalar,
  onValue: (stateId: string, next: StructuredUiScalar) => void,
  numberDraft: string | undefined,
  onNumberDraft: (node: StructuredUiInputNode, value: string) => void,
  onNumberBlur: (node: StructuredUiInputNode) => void,
) {
  const id = structuredUiDomId(instanceId, node.id);
  if (node.type === "checkbox") {
    return <label className="structured-ui__field structured-ui__field--checkbox" htmlFor={id}>
      <input id={id} type="checkbox" checked={value === true} onChange={(event) => onValue(node.state_id, event.currentTarget.checked)} />
      <span>{node.label}</span>
    </label>;
  }
  if (node.type === "select") {
    return <label className="structured-ui__field" htmlFor={id}>
      <span>{node.label}</span>
      <select id={id} value={typeof value === "string" ? value : ""} onChange={(event) => onValue(node.state_id, event.currentTarget.value)}>
        {node.options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>;
  }
  if (node.type === "slider") {
    const numeric = typeof value === "number" ? value : node.minimum;
    return <label className="structured-ui__field structured-ui__field--slider" htmlFor={id}>
      <span>{node.label}</span>
      <span className="structured-ui__slider-row">
        <input id={id} type="range" min={node.minimum} max={node.maximum} step={node.step} value={numeric} onChange={(event) => onValue(node.state_id, Number(event.currentTarget.value))} />
        <output htmlFor={id}>{scalarText(numeric)}</output>
      </span>
    </label>;
  }
  if (node.type === "textarea") {
    return <label className="structured-ui__field" htmlFor={id}>
      <span>{node.label}</span>
      <textarea id={id} maxLength={4000} value={typeof value === "string" ? value : ""} onChange={(event) => onValue(node.state_id, event.currentTarget.value)} />
    </label>;
  }
  const isNumber = node.input_type === "number";
  return <label className="structured-ui__field" htmlFor={id}>
    <span>{node.label}</span>
    <input
      id={id}
      type="text"
      inputMode={isNumber ? "decimal" : undefined}
      maxLength={isNumber ? 32 : 4000}
      aria-invalid={isNumber && numberDraft !== undefined && parseNumericDraft(numberDraft, node) === null}
      value={isNumber ? numberDraft ?? scalarText(value) : scalarText(value)}
      onChange={(event) => {
        if (!isNumber) {
          onValue(node.state_id, event.currentTarget.value);
          return;
        }
        onNumberDraft(node, event.currentTarget.value);
      }}
      onBlur={isNumber ? () => onNumberBlur(node) : undefined}
    />
  </label>;
}

function renderTable(node: Extract<StructuredUiNode, { type: "table" }>) {
  return <div className="structured-ui__table-scroll">
    <table className="structured-ui__table">
      {node.caption ? <caption><StructuredUiInlineMarkdown text={node.caption} /></caption> : null}
      <thead><tr>{node.columns.map((column, index) => <th key={`${column}-${index}`} scope="col"><StructuredUiInlineMarkdown text={column} /></th>)}</tr></thead>
      <tbody>{node.rows.map((row, rowIndex) => <tr key={`row-${rowIndex}`}>
        {row.map((cell, cellIndex) => <td key={`cell-${cellIndex}`}><StructuredUiInlineMarkdown text={scalarText(cell)} /></td>)}
      </tr>)}</tbody>
    </table>
  </div>;
}

function renderDiagram(node: Extract<StructuredUiNode, { type: "diagram" }>) {
  const items = new Map(node.items.map((item) => [item.id, item.label]));
  return <section className="structured-ui__diagram" aria-label={node.title || "Diagram"}>
    {node.title ? <h3 className="structured-ui__section-title"><StructuredUiInlineMarkdown text={node.title} /></h3> : null}
    <ol className="structured-ui__diagram-items">
      {node.items.map((item) => <li key={item.id}><span className="structured-ui__diagram-node"><StructuredUiInlineMarkdown text={item.label} /></span></li>)}
    </ol>
    {node.edges.length > 0 ? <ul className="structured-ui__diagram-edges">
      {node.edges.map((edge, index) => <li key={`${edge.source}-${edge.target}-${index}`}>
        <span><StructuredUiInlineMarkdown text={items.get(edge.source) ?? ""} /></span><span className="structured-ui__diagram-arrow" aria-hidden="true">→</span><span><StructuredUiInlineMarkdown text={items.get(edge.target) ?? ""} /></span>
        {edge.label ? <small><StructuredUiInlineMarkdown text={edge.label} /></small> : null}
      </li>)}
    </ul> : null}
  </section>;
}

function renderImage(node: Extract<StructuredUiNode, { type: "image" }>, ui: StructuredUiRuntime) {
  const image = ui.images.find((candidate) => candidate.ref === node.ref);
  if (!image) return <span className="structured-ui__image-missing">{node.alt}</span>;
  return <figure className="structured-ui__image">
    {/* The URL is a validated, signed same-origin relay path from the server. */}
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img src={image.url} alt={node.alt} loading="lazy" referrerPolicy="no-referrer" />
    {image.source_title && isHttpUrl(image.source_url)
      ? <figcaption><a href={image.source_url} target="_blank" rel="noopener noreferrer">{image.source_title}</a></figcaption>
      : null}
  </figure>;
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (url.protocol === "http:" || url.protocol === "https:") && Boolean(url.host) && !url.username && !url.password;
  } catch {
    return false;
  }
}

function tabsLayout(
  instanceId: string,
  node: StructuredUiLayoutNode,
  index: number,
  selectIndex: (nodeId: string, nextIndex: number) => void,
  renderChild: (id: string) => ReactNode,
) {
  const selectedIndex = Math.min(Math.max(index, 0), Math.max(node.children.length - 1, 0));
  const label = node.title || "Sections";
  return <section className="structured-ui__tabs" aria-label={label}>
    {node.title ? <h3 className="structured-ui__section-title"><StructuredUiInlineMarkdown text={node.title} /></h3> : null}
    <div className="structured-ui__tab-list" role="tablist" aria-label={label}>
      {node.children.map((child, childIndex) => <button
        key={child}
        type="button"
        role="tab"
        id={structuredUiDomId(instanceId, node.id, `tab-${childIndex}`)}
        aria-selected={selectedIndex === childIndex}
        aria-controls={structuredUiDomId(instanceId, node.id, "panel")}
        tabIndex={selectedIndex === childIndex ? 0 : -1}
        className={selectedIndex === childIndex ? "structured-ui__tab is-active" : "structured-ui__tab"}
        onClick={() => selectIndex(node.id, childIndex)}
        onKeyDown={(event) => {
          const next = event.key === "ArrowRight"
            ? (childIndex + 1) % node.children.length
            : event.key === "ArrowLeft"
              ? (childIndex - 1 + node.children.length) % node.children.length
              : event.key === "Home"
                ? 0
                : event.key === "End"
                  ? node.children.length - 1
                  : null;
          if (next === null) return;
          event.preventDefault();
          selectIndex(node.id, next);
          event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role='tab']")[next]?.focus();
        }}
      ><StructuredUiInlineMarkdown text={node.labels[childIndex] ?? `Tab ${childIndex + 1}`} /></button>)}
    </div>
    {node.children[selectedIndex] ? <div
      className="structured-ui__tab-panel"
      id={structuredUiDomId(instanceId, node.id, "panel")}
      role="tabpanel"
      aria-labelledby={structuredUiDomId(instanceId, node.id, `tab-${selectedIndex}`)}
    >
      {renderChild(node.children[selectedIndex])}
    </div> : null}
  </section>;
}

function stepsLayout(
  node: StructuredUiLayoutNode,
  index: number,
  selectIndex: (nodeId: string, nextIndex: number) => void,
  renderChild: (id: string) => ReactNode,
  labels: { back: string; next: string },
) {
  const selectedIndex = Math.min(Math.max(index, 0), Math.max(node.children.length - 1, 0));
  return <section className="structured-ui__steps" aria-label={node.title || "Steps"}>
    {node.title ? <h3 className="structured-ui__section-title"><StructuredUiInlineMarkdown text={node.title} /></h3> : null}
    <div className="structured-ui__step-heading">
      <span><StructuredUiInlineMarkdown text={node.labels[selectedIndex] ?? `Step ${selectedIndex + 1}`} /></span>
      <span>{selectedIndex + 1} / {node.children.length}</span>
    </div>
    <progress max={Math.max(node.children.length, 1)} value={selectedIndex + 1} aria-label="Step progress" />
    {node.children[selectedIndex] ? <div className="structured-ui__step-content">{renderChild(node.children[selectedIndex])}</div> : null}
    <div className="structured-ui__step-actions">
      <button type="button" onClick={() => selectIndex(node.id, nextIndex(selectedIndex, node.children.length, -1))} disabled={selectedIndex === 0}>{labels.back}</button>
      <button type="button" onClick={() => selectIndex(node.id, nextIndex(selectedIndex, node.children.length, 1))} disabled={selectedIndex >= node.children.length - 1}>{labels.next}</button>
    </div>
  </section>;
}

function timelineLayout(node: StructuredUiLayoutNode, renderChild: (id: string) => ReactNode) {
  return <section className="structured-ui__timeline" aria-label={node.title || "Timeline"}>
    {node.title ? <h3 className="structured-ui__section-title"><StructuredUiInlineMarkdown text={node.title} /></h3> : null}
    <ol>{node.children.map((child, index) => <li key={child}>
      <div className="structured-ui__timeline-label"><StructuredUiInlineMarkdown text={node.labels[index] ?? `Item ${index + 1}`} /></div>
      <div className="structured-ui__timeline-content">{renderChild(child)}</div>
    </li>)}</ol>
  </section>;
}

function layoutNode(
  instanceId: string,
  node: StructuredUiLayoutNode,
  activeTabs: Record<string, number>,
  activeSteps: ActiveSteps,
  selectTab: (nodeId: string, nextIndex: number) => void,
  selectStep: (nodeId: string, nextIndex: number) => void,
  renderChild: (id: string) => ReactNode,
  stepLabels: { back: string; next: string },
) {
  if (node.type === "tabs") return tabsLayout(instanceId, node, activeTabs[node.id] ?? 0, selectTab, renderChild);
  if (node.type === "steps") return stepsLayout(node, activeSteps[node.id] ?? 0, selectStep, renderChild, stepLabels);
  if (node.type === "timeline") return timelineLayout(node, renderChild);
  const children = node.children.map((child) => <div key={child} className="structured-ui__layout-child">{renderChild(child)}</div>);
  if (node.type === "card") return <section className="structured-ui__card">
    {node.title ? <h3 className="structured-ui__section-title"><StructuredUiInlineMarkdown text={node.title} /></h3> : null}{children}
  </section>;
  if (node.type === "row") return <div className="structured-ui__row">{children}</div>;
  if (node.type === "grid") return <div className="structured-ui__grid" style={{ "--structured-grid-columns": node.columns } as CSSProperties}>{children}</div>;
  return <div className="structured-ui__column">{children}</div>;
}

function StructuredUiContent({ onCompose, disabled, stateScope, runtime }: Props & { runtime: StructuredUiRuntime }) {
  const { t } = useTranslation();
  const instanceId = useId();
  const renderStartedAt = typeof window === "undefined" ? null : window.performance.now();
  const [stateValues, setStateValues] = useState<Record<string, StructuredUiScalar>>(() => defaultStateValues(runtime));
  const [activeTabs, setActiveTabs] = useState<Record<string, number>>({});
  const [activeSteps, setActiveSteps] = useState<ActiveSteps>({});
  const [numberDrafts, setNumberDrafts] = useState<Record<string, string>>({});
  const [localError, setLocalError] = useState<string | null>(null);
  const [hydratedScope, setHydratedScope] = useState<string | null>(null);
  const previousScopeRef = useRef<string | null | undefined>(undefined);
  const liveSelectionsRef = useRef<PersistedSelections>({ selected: {}, tabs: {} });
  const scopeKey = structuredUiMetricsScopeFromStateScope(stateScope);

  const effectiveValues = useMemo(() => ({ ...defaultStateValues(runtime), ...stateValues }), [runtime, stateValues]);
  const nodesById = useMemo(() => new Map(runtime.nodes.map((node) => [node.id, node])), [runtime]);
  const evaluator = useMemo(() => new StructuredUiExpressionEvaluator(runtime, effectiveValues), [runtime, effectiveValues]);
  liveSelectionsRef.current = persistedSelections(runtime, effectiveValues, activeTabs);

  useEffect(() => {
    activateStructuredUiMetricsScope(scopeKey);
  }, [scopeKey]);

  useLayoutEffect(() => {
    if (!scopeKey || renderStartedAt === null) return;
    // React's standard production build omits Profiler onRender; record the local render-to-commit interval as an approximation.
    const renderMs = window.performance.now() - renderStartedAt;
    if (Number.isFinite(renderMs) && renderMs >= 0) {
      recordStructuredUiMetric(scopeKey, runtime.id, { render_ms: Math.ceil(renderMs) });
    }
  });

  useEffect(() => {
    const previousScope = previousScopeRef.current;
    const nextScope = stateScope ?? null;
    if (previousScope === nextScope) return;
    previousScopeRef.current = nextScope;
    if (previousScope && stateScope && isFinalizedBlockScope(previousScope, stateScope)) {
      savePersistedSelections(stateScope, liveSelectionsRef.current);
      try {
        window.localStorage.removeItem(scopeStorageKey(previousScope));
      } catch {
        // Migration is best-effort; the live React state remains authoritative.
      }
      setHydratedScope(stateScope);
      return;
    }
    const defaults = defaultStateValues(runtime);
    const persisted = stateScope ? readPersistedSelections(runtime, stateScope) : { selected: {}, tabs: {} };
    setStateValues({ ...defaults, ...persisted.selected });
    setActiveTabs(persisted.tabs);
    setActiveSteps({});
    setNumberDrafts({});
    setLocalError(null);
    setHydratedScope(nextScope);
  }, [runtime, stateScope]);

  useEffect(() => {
    if (!stateScope || hydratedScope !== stateScope) return;
    savePersistedSelections(stateScope, persistedSelections(runtime, effectiveValues, activeTabs));
  }, [runtime, stateScope, hydratedScope, effectiveValues, activeTabs]);

  const recordAction = useCallback((success: boolean, composed = false) => {
    setLocalError(success ? null : t("chat.toolApproval.error.invalid_content"));
    if (!scopeKey) return;
    recordStructuredUiMetric(scopeKey, runtime.id, {
      action_count: 1,
      action_error_count: success ? 0 : 1,
      compose_count: success && composed ? 1 : 0,
    });
  }, [runtime.id, scopeKey, t]);

  const updateState = useCallback((stateId: string, nextValue: StructuredUiScalar, clearNumberDrafts = true) => {
    if (!stateUpdateIsValid(runtime, stateId, nextValue)) {
      recordAction(false);
      return;
    }
    if (clearNumberDrafts) {
      setNumberDrafts((current) => {
        const next = { ...current };
        for (const node of runtime.nodes) {
          if ((node.type === "input" && node.input_type === "number") && node.state_id === stateId) delete next[node.id];
        }
        return next;
      });
    }
    if (Object.is(effectiveValues[stateId], nextValue)) return;
    setStateValues((current) => ({ ...current, [stateId]: nextValue }));
    recordAction(true);
  }, [effectiveValues, recordAction, runtime]);

  const updateNumberDraft = useCallback((node: StructuredUiInputNode, rawValue: string) => {
    setNumberDrafts((current) => ({ ...current, [node.id]: rawValue }));
    if (!rawValue.trim()) {
      setLocalError(null);
      return;
    }
    const parsed = parseNumericDraft(rawValue, node);
    if (parsed !== null) updateState(node.state_id, parsed, false);
  }, [updateState]);

  const blurNumberDraft = useCallback((node: StructuredUiInputNode) => {
    const rawValue = numberDrafts[node.id];
    if (rawValue === undefined) return;
    const parsed = parseNumericDraft(rawValue, node);
    if (parsed === null) {
      recordAction(false);
      return;
    }
    setNumberDrafts((current) => {
      const next = { ...current };
      delete next[node.id];
      return next;
    });
    setLocalError(null);
    updateState(node.state_id, parsed);
  }, [numberDrafts, recordAction, updateState]);

  const selectTab = useCallback((nodeId: string, nextIndex: number) => {
    const node = nodesById.get(nodeId);
    if (!node || node.type !== "tabs" || nextIndex < 0 || nextIndex >= node.children.length) return;
    if ((activeTabs[nodeId] ?? 0) === nextIndex) return;
    setActiveTabs((current) => ({ ...current, [nodeId]: nextIndex }));
    recordAction(true);
  }, [activeTabs, nodesById, recordAction]);

  const selectStep = useCallback((nodeId: string, nextIndex: number) => {
    const node = nodesById.get(nodeId);
    if (!node || node.type !== "steps" || nextIndex < 0 || nextIndex >= node.children.length) return;
    if ((activeSteps[nodeId] ?? 0) === nextIndex) return;
    setActiveSteps((current) => ({ ...current, [nodeId]: nextIndex }));
    recordAction(true);
  }, [activeSteps, nodesById, recordAction]);

  const composeText = useCallback((text: string) => {
    if (disabled || !onCompose) return;
    const invalidDraft = runtime.nodes.some((node) => node.type === "input" && node.input_type === "number"
      && numberDrafts[node.id] !== undefined && parseNumericDraft(numberDrafts[node.id], node) === null);
    if (invalidDraft || Array.from(text).length > 30_000) {
      recordAction(false);
      return;
    }
    try {
      onCompose(text);
      recordAction(true, true);
    } catch {
      recordAction(false);
    }
  }, [disabled, numberDrafts, onCompose, recordAction, runtime.nodes]);

  const invokeButton = useCallback((node: StructuredUiButtonNode) => {
    const action = node.action;
    if (action.type === "compose") {
      if (disabled || !onCompose) return;
      const text = buildActionComposeText(action, effectiveValues);
      if (!text) {
        recordAction(false);
        return;
      }
      composeText(text);
      return;
    }
    if (action.type === "reset") {
      if (action.state_id) {
        const initial = runtime.state.find((state) => state.id === action.state_id)?.initial;
        if (initial === undefined) {
          recordAction(false);
          return;
        }
        updateState(action.state_id, initial);
        return;
      }
      setStateValues(defaultStateValues(runtime));
      recordAction(true);
      return;
    }
    if (!action.state_id || !action.value) {
      recordAction(false);
      return;
    }
    const value = evaluator.resolve(action.value);
    if (value === undefined || Array.isArray(value)) {
      recordAction(false);
      return;
    }
    updateState(action.state_id, value);
  }, [composeText, disabled, effectiveValues, evaluator, onCompose, recordAction, runtime, updateState]);

  const pointBudget = chartPointBudget();
  const renderNode = (nodeId: string): ReactNode => {
    const node = nodesById.get(nodeId);
    if (!node) return null;
    if (node.visible_when && !evaluator.evaluate(node.visible_when)) return null;
    switch (node.type) {
      case "text": {
        const binding = node.binding ? evaluator.evaluate(node.binding) : undefined;
        return <p className="structured-ui__text"><StructuredUiInlineMarkdown text={node.text} />{binding !== undefined ? <>
          {node.text ? " " : ""}<span><StructuredUiInlineMarkdown text={expressionText(binding)} /></span>
        </> : null}</p>;
      }
      case "heading": {
        const binding = node.binding ? evaluator.evaluate(node.binding) : undefined;
        const text = `${node.text}${binding !== undefined ? `${node.text ? " " : ""}${expressionText(binding)}` : ""}`;
        return <>{namedHeading(node.level, <StructuredUiInlineMarkdown text={text} />)}</>;
      }
      case "markdown":
        return <StructuredUiMarkdown text={node.text} />;
      case "row":
      case "column":
      case "grid":
      case "card":
      case "tabs":
      case "steps":
      case "timeline":
        return layoutNode(instanceId, node, activeTabs, activeSteps, selectTab, selectStep, renderNode, { back: t("common.back"), next: t("common.next") });
      case "table":
        return renderTable(node);
      case "chart":
        return <StructuredUiChart node={node} uiId={instanceId} series={prepareStructuredUiChartSeries(node, evaluator, pointBudget)} />;
      case "input":
      case "textarea":
      case "checkbox":
      case "select":
      case "slider":
        return renderInput(instanceId, node, effectiveValues[node.state_id] ?? false, updateState, numberDrafts[node.id], updateNumberDraft, blurNumberDraft);
      case "button":
        return <button className="structured-ui__action-button" type="button" disabled={node.action.type === "compose" && (disabled || !onCompose)} onClick={() => invokeButton(node)}>{node.label}</button>;
      case "choice":
        return <div className="structured-ui__choice">
          <InteractiveButtons
            buttons={{ ...node.buttons, options: node.buttons.options ?? undefined }}
            onCompose={onCompose ? composeText : undefined}
            disabled={disabled}
          />
        </div>;
      case "image":
        return renderImage(node, runtime);
      case "divider":
        return <hr className="structured-ui__divider" />;
      case "diagram":
        return renderDiagram(node);
      default:
        return null;
    }
  };

  return <div className="structured-ui" data-structured-ui-id={runtime.id}>
    {localError ? <p className="structured-ui__error" role="alert">{localError}</p> : null}
    {renderNode(runtime.root_id)}
    {runtime.sources?.length ? <StructuredUiSources sources={runtime.sources} label={t("chat.generatedUiSources")} /> : null}
  </div>;
}

function StructuredUiSources({ sources, label }: { sources: StructuredUiSource[]; label: string }) {
  return <section className="structured-ui__sources" aria-label={label}>
    <h3 className="structured-ui__section-title">{label}</h3>
    <ol>
      {sources.map((source, index) => isHttpUrl(source.url) ? <li key={`${source.url}-${index}`}>
        <a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a>
      </li> : null)}
    </ol>
  </section>;
}

type ErrorBoundaryProps = { fallbackText: string; errorLabel: string; onFailure: () => void; children: ReactNode };
type ErrorBoundaryState = { failed: boolean };

class StructuredUiRenderBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    this.props.onFailure();
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return <div className="structured-ui__fallback" role="alert">
      <p>{this.props.errorLabel}</p>
      <p>{this.props.fallbackText}</p>
    </div>;
  }
}

export function StructuredUiRenderer({ ui, onCompose, disabled = false, stateScope }: Props) {
  const { t } = useTranslation();
  const runtime = useMemo(() => {
    const parsed = parseStructuredUiV1(ui);
    return parsed ? getStructuredUiRuntime(parsed) : null;
  }, [ui]);
  if (!runtime) return <div className="structured-ui__fallback">{ui.fallback_text}</div>;
  const scopeKey = structuredUiMetricsScopeFromStateScope(stateScope);
  return <StructuredUiRenderBoundary
    key={runtime.id}
    fallbackText={runtime.fallback_text}
    errorLabel={t("common.error")}
    onFailure={() => {
      if (scopeKey) recordStructuredUiMetric(scopeKey, runtime.id, { action_count: 1, action_error_count: 1 });
    }}
  >
    <StructuredUiContent ui={ui} onCompose={onCompose} disabled={disabled} stateScope={stateScope} runtime={runtime} />
  </StructuredUiRenderBoundary>;
}
