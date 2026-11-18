// Anonymous, value-free native UI telemetry. It remains in memory and is sent
// only when a later normal chat request explicitly snapshots this room's buffer.
export type StructuredUiMetricRecord = {
  block_id: string;
  render_ms: number;
  action_count: number;
  action_error_count: number;
  compose_count: number;
};

export type StructuredUiMetricsSnapshot = {
  snapshotId: string;
  metrics: readonly StructuredUiMetricRecord[];
};

type MetricDelta = Omit<StructuredUiMetricRecord, "block_id">;
type PendingBuffer = { snapshotId: string; metrics: readonly StructuredUiMetricRecord[] };
type ScopeBuffer = { current: Map<string, StructuredUiMetricRecord>; pending: PendingBuffer | null };

const STORAGE_SCOPE_PREFIX = "chatcore.structured-ui:";
const MAX_METRIC_RECORDS = 20;
const MAX_RENDER_MS = 60_000;
const MAX_COUNTER = 10_000;

const buffers = new Map<string, ScopeBuffer>();
let activeScope: string | null = null;
let nextSnapshotId = 1;

function clamp(value: number, maximum: number): number {
  if (!Number.isFinite(value) || value <= 0) return 0;
  return Math.min(value, maximum);
}

function isSafeScope(scopeKey: string): boolean {
  return scopeKey.length > 0 && scopeKey.length <= 512 && !scopeKey.startsWith(STORAGE_SCOPE_PREFIX);
}

export function structuredUiMetricsScopeFromStateScope(stateScope?: string): string | null {
  if (!stateScope || stateScope.length > 2048) return null;
  const segments = stateScope.split(":");
  if (segments.length !== 4 || segments.some((segment) => !segment)) return null;
  try {
    const decoded = segments.map((segment) => decodeURIComponent(segment));
    if (decoded.some((segment) => segment.length === 0) || !decoded[0].startsWith("user:")) return null;
  } catch {
    return null;
  }
  return `${segments[0]}:${segments[1]}`;
}

function getBuffer(scopeKey: string): ScopeBuffer {
  let buffer = buffers.get(scopeKey);
  if (!buffer) {
    buffer = { current: new Map(), pending: null };
    buffers.set(scopeKey, buffer);
  }
  return buffer;
}

/** Remove prior-room buffers when the active user/room changes. */
export function activateStructuredUiMetricsScope(scopeKey: string | null): void {
  if (activeScope === scopeKey) return;
  if (activeScope) buffers.delete(activeScope);
  if (scopeKey === null) buffers.clear();
  activeScope = scopeKey;
}

/** Record counters only; UI state and entered values are never accepted here. */
export function recordStructuredUiMetric(scopeKey: string, blockId: string, delta: Partial<MetricDelta>): void {
  if (!isSafeScope(scopeKey) || (activeScope && activeScope !== scopeKey) || !/^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/.test(blockId)) return;
  const buffer = getBuffer(scopeKey);
  if (buffer.current.size >= MAX_METRIC_RECORDS && !buffer.current.has(blockId)) return;
  let current = buffer.current.get(blockId);
  if (!current) {
    current = { block_id: blockId, render_ms: 0, action_count: 0, action_error_count: 0, compose_count: 0 };
    buffer.current.set(blockId, current);
  }
  current.render_ms = clamp(current.render_ms + clamp(delta.render_ms ?? 0, MAX_RENDER_MS), MAX_RENDER_MS);
  current.action_count = clamp(current.action_count + clamp(delta.action_count ?? 0, MAX_COUNTER), MAX_COUNTER);
  current.action_error_count = clamp(current.action_error_count + clamp(delta.action_error_count ?? 0, MAX_COUNTER), MAX_COUNTER);
  current.compose_count = clamp(current.compose_count + clamp(delta.compose_count ?? 0, MAX_COUNTER), MAX_COUNTER);
}

/** Read the same immutable snapshot until it is acknowledged. */
export function readStructuredUiMetrics(scopeKey: string): StructuredUiMetricsSnapshot | null {
  if (!isSafeScope(scopeKey)) return null;
  const buffer = buffers.get(scopeKey);
  if (!buffer) return null;
  if (!buffer.pending && buffer.current.size > 0) {
    const metrics = Array.from(buffer.current.values(), (metric) => Object.freeze({ ...metric }));
    buffer.current.clear();
    buffer.pending = {
      snapshotId: String(nextSnapshotId++),
      metrics: Object.freeze(metrics),
    };
  }
  if (!buffer.pending) return null;
  return Object.freeze({ snapshotId: buffer.pending.snapshotId, metrics: buffer.pending.metrics });
}

/** Acknowledge only a successful request's snapshot; later events stay buffered. */
export function ackStructuredUiMetrics(scopeKey: string, snapshotId: string): void {
  const buffer = buffers.get(scopeKey);
  if (!buffer?.pending || buffer.pending.snapshotId !== snapshotId) return;
  buffer.pending = null;
  if (buffer.current.size === 0) buffers.delete(scopeKey);
}

export function clearStructuredUiMetrics(scopeKey?: string): void {
  if (scopeKey) {
    buffers.delete(scopeKey);
    if (activeScope === scopeKey) activeScope = null;
    return;
  }
  buffers.clear();
  activeScope = null;
}
