import type { CSSProperties } from "react";

import type { StructuredUiChartNode } from "../../lib/chat_page/structured_ui_contract";
import { StructuredUiExpressionEvaluator } from "../../lib/chat_page/structured_ui_expressions";

const VIEW_WIDTH = 600;
const VIEW_HEIGHT = 280;
const PLOT = { left: 96, right: 48, top: 18, bottom: 42 };
const SERIES_COLORS = ["var(--primary-color)", "var(--info-color)", "var(--accent-color)", "var(--success-color)", "var(--neutral-button)"];

type PointBudget = { remaining: number };
export type StructuredUiChartSeries = { label: string; values: number[] };
type Props = {
  node: StructuredUiChartNode;
  uiId: string;
  series: StructuredUiChartSeries[];
};

export function prepareStructuredUiChartSeries(
  node: StructuredUiChartNode,
  evaluator: StructuredUiExpressionEvaluator,
  pointBudget: PointBudget,
): StructuredUiChartSeries[] {
  const data: StructuredUiChartSeries[] = [];
  for (const series of node.series) {
    const bound = series.binding ? evaluator.evaluate(series.binding) : undefined;
    const values = Array.isArray(bound) && bound.every((value): value is number => typeof value === "number" && Number.isFinite(value))
      ? bound
      : typeof bound === "number" && Number.isFinite(bound)
        ? [bound]
        : series.values;
    const count = Math.min(values.length, Math.max(0, pointBudget.remaining));
    const clippedValues = values.slice(0, count).filter(Number.isFinite);
    pointBudget.remaining -= clippedValues.length;
    data.push({ label: series.label, values: clippedValues });
  }
  return data;
}

function chartTicks(node: StructuredUiChartNode, count: number): Array<{ index: number; label: string }> {
  if (count <= 0) return [];
  const tickCount = Math.min(5, count);
  const indexes = Array.from({ length: tickCount }, (_, index) => tickCount === 1 ? 0 : Math.round((index * (count - 1)) / (tickCount - 1)));
  return Array.from(new Set(indexes), (index) => ({ index, label: node.labels[index] ?? String(index + 1) }));
}

function seriesColor(index: number): string {
  return SERIES_COLORS[index % SERIES_COLORS.length];
}

function legend(series: StructuredUiChartSeries[], prefix: string) {
  return <ul className="structured-ui__chart-legend">
    {series.map((item, index) => (
      <li key={`${prefix}-${item.label}-${index}`} style={{ "--structured-series-color": seriesColor(index) } as CSSProperties}>
        <span className="structured-ui__chart-swatch" aria-hidden="true" />
        <span>{item.label}</span>
      </li>
    ))}
  </ul>;
}

function renderAxes(min: number, max: number, plotHeight: number) {
  const count = 4;
  return <g className="structured-ui__chart-axis" aria-hidden="true">
    {Array.from({ length: count + 1 }, (_, index) => {
      const ratio = index / count;
      const y = PLOT.top + plotHeight * ratio;
      const value = max - (max - min) * ratio;
      return <g key={`tick-${index}`}>
        <line x1={PLOT.left} x2={VIEW_WIDTH - PLOT.right} y1={y} y2={y} />
        <text x={PLOT.left - 8} y={y + 4} textAnchor="end">{new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)}</text>
      </g>;
    })}
  </g>;
}

function lineChart(node: StructuredUiChartNode, series: StructuredUiChartSeries[], id: string) {
  const plotWidth = VIEW_WIDTH - PLOT.left - PLOT.right;
  const plotHeight = VIEW_HEIGHT - PLOT.top - PLOT.bottom;
  const count = Math.max(...series.map((item) => item.values.length), 0);
  const allValues = series.flatMap((item) => item.values);
  const rawMin = allValues.length ? Math.min(...allValues) : 0;
  const rawMax = allValues.length ? Math.max(...allValues) : 1;
  const padding = rawMin === rawMax ? Math.max(Math.abs(rawMin) * 0.1, 1) : (rawMax - rawMin) * 0.08;
  const min = rawMin - padding;
  const max = rawMax + padding;
  const ticks = chartTicks(node, count);

  return <svg className="structured-ui__chart-svg" viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`} role="img" aria-labelledby={`${id}-title`}>
    <title id={`${id}-title`}>{node.title || "Line chart"}</title>
    {renderAxes(min, max, plotHeight)}
    {series.map((item, seriesIndex) => {
      if (item.values.length === 0) return null;
      const points = item.values.map((value, index) => {
        const x = PLOT.left + (item.values.length <= 1 ? plotWidth / 2 : (index / (item.values.length - 1)) * plotWidth);
        const y = PLOT.top + ((max - value) / (max - min)) * plotHeight;
        return `${x},${y}`;
      }).join(" ");
      return <polyline key={`${item.label}-${seriesIndex}`} points={points} style={{ "--structured-series-color": seriesColor(seriesIndex) } as CSSProperties} />;
    })}
    {ticks.map((tick) => {
      const x = PLOT.left + (count <= 1 ? plotWidth / 2 : (tick.index / (count - 1)) * plotWidth);
      return <text key={`${tick.index}-${tick.label}`} className="structured-ui__chart-x-label" x={x} y={VIEW_HEIGHT - 12} textAnchor="middle">{tick.label}</text>;
    })}
  </svg>;
}

function barChart(node: StructuredUiChartNode, series: StructuredUiChartSeries[], id: string) {
  const plotWidth = VIEW_WIDTH - PLOT.left - PLOT.right;
  const plotHeight = VIEW_HEIGHT - PLOT.top - PLOT.bottom;
  const count = Math.max(...series.map((item) => item.values.length), 0);
  const allValues = series.flatMap((item) => item.values);
  const min = Math.min(0, ...(allValues.length ? allValues : [0]));
  const rawMax = Math.max(0, ...(allValues.length ? allValues : [1]));
  const max = rawMax === min ? min + 1 : rawMax + Math.max((rawMax - min) * 0.08, 0.5);
  const yFor = (value: number) => PLOT.top + ((max - value) / (max - min)) * plotHeight;
  const groupWidth = count ? plotWidth / count : plotWidth;
  const barWidth = Math.max(0.25, (groupWidth * 0.72) / Math.max(series.length, 1));
  const ticks = chartTicks(node, count);

  return <svg className="structured-ui__chart-svg" viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`} role="img" aria-labelledby={`${id}-title`}>
    <title id={`${id}-title`}>{node.title || "Bar chart"}</title>
    {renderAxes(min, max, plotHeight)}
    {series.flatMap((item, seriesIndex) => item.values.map((value, index) => {
      const x = PLOT.left + index * groupWidth + (groupWidth - barWidth * series.length) / 2 + seriesIndex * barWidth;
      const y = yFor(Math.max(value, 0));
      const bottom = yFor(Math.min(value, 0));
      return <rect key={`${item.label}-${index}`} x={x} y={y} width={barWidth} height={Math.max(bottom - y, 0.5)} style={{ "--structured-series-color": seriesColor(seriesIndex) } as CSSProperties} />;
    }))}
    {ticks.map((tick) => {
      const x = PLOT.left + (tick.index + 0.5) * groupWidth;
      return <text key={`${tick.index}-${tick.label}`} className="structured-ui__chart-x-label" x={x} y={VIEW_HEIGHT - 12} textAnchor="middle">{tick.label}</text>;
    })}
  </svg>;
}

function pieChart(node: StructuredUiChartNode, series: StructuredUiChartSeries[], id: string) {
  const count = Math.max(...series.map((item) => item.values.length), 0);
  const slices = Array.from({ length: count }, (_, index) => ({
    label: node.labels[index] ?? String(index + 1),
    value: series.reduce((total, item) => total + Math.max(item.values[index] ?? 0, 0), 0),
  })).filter((slice) => slice.value > 0);
  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  if (!total) return <p className="structured-ui__chart-empty">No positive values</p>;
  let angle = -Math.PI / 2;
  const centerX = 170;
  const centerY = 135;
  const radius = 96;
  const arcs = slices.map((slice, index) => {
    const endAngle = angle + (slice.value / total) * Math.PI * 2;
    const x1 = centerX + radius * Math.cos(angle);
    const y1 = centerY + radius * Math.sin(angle);
    const x2 = centerX + radius * Math.cos(endAngle);
    const y2 = centerY + radius * Math.sin(endAngle);
    const largeArc = endAngle - angle > Math.PI ? 1 : 0;
    const path = `M ${centerX} ${centerY} L ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2} Z`;
    angle = endAngle;
    return { ...slice, path, index };
  });
  return <svg className="structured-ui__chart-svg structured-ui__chart-svg--pie" viewBox="0 0 600 280" role="img" aria-labelledby={`${id}-title`}>
    <title id={`${id}-title`}>{node.title || "Pie chart"}</title>
    {arcs.map((arc) => <g key={`${arc.label}-${arc.index}`}>
      <path d={arc.path} style={{ "--structured-series-color": seriesColor(arc.index) } as CSSProperties} />
      <text x="330" y={38 + arc.index * 27}>{arc.label}: {new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(arc.value)}</text>
    </g>)}
  </svg>;
}

export function StructuredUiChart({ node, uiId, series }: Props) {
  const id = `${uiId}-${node.id}`;
  const hasValues = series.some((item) => item.values.length > 0);
  return <figure className="structured-ui__chart">
    {node.title ? <figcaption>{node.title}</figcaption> : null}
    {hasValues ? (
      <div className="structured-ui__chart-viewport">
        {node.kind === "bar" ? barChart(node, series, id) : node.kind === "pie" ? pieChart(node, series, id) : lineChart(node, series, id)}
      </div>
    ) : <p className="structured-ui__chart-empty">No chart data</p>}
    {node.kind !== "pie" ? legend(series, id) : null}
    {node.kind === "pie" && series.length > 1 ? legend(series, id) : null}
    <div className="structured-ui__chart-data" aria-hidden="true">
      {series.map((item, index) => <span key={`${item.label}-${index}`}>{item.label}</span>)}
    </div>
  </figure>;
}

export type { PointBudget };
