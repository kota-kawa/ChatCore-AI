// 回答までのステップ（回答の実行記録）の正規化と、パーツ列への載せ方を持つ。
// 規則（種類・状態・上限・URL の検証）は services/answer_trace.py の normalize_answer_trace と揃えている。
// SSE・履歴 API・共有チャット・端末に保存した状態のどこから来た値も、ここを通してから画面に渡す。
// Normalization of the steps to the answer (the answer's execution record) and how it sits in the part list.
// The rules (kinds, statuses, limits, URL validation) mirror normalize_answer_trace in services/answer_trace.py.
// A value from the SSE stream, the history API, a shared chat or the state saved on the device passes
// through here before it reaches the screen.

import type {
  AnswerTraceSource,
  AnswerTraceStep,
  AnswerTraceStepKind,
  AnswerTraceStepStatus,
  AnswerTraceV1,
  ChatMessagePart,
} from "./types";
import { asRecord } from "../utils";

const ANSWER_TRACE_VERSION = 1;

const STEP_KINDS: ReadonlySet<string> = new Set<AnswerTraceStepKind>([
  "decide",
  "search",
  "reuse",
  "read",
  "follow",
  "review",
  "answer",
  "warning",
  "knowledge",
  "prompt",
  "info",
]);
const DEFAULT_STEP_KIND: AnswerTraceStepKind = "info";
const STEP_STATUSES: ReadonlySet<string> = new Set<AnswerTraceStepStatus>(["running", "done", "failed"]);
const DEFAULT_STEP_STATUS: AnswerTraceStepStatus = "done";

const MAX_STEPS = 60;
const MAX_STEP_SOURCES = 40;
const MAX_STEP_CHIPS = 8;
const STEP_TITLE_MAX_CHARS = 120;
const STEP_DETAIL_MAX_CHARS = 260;
const STEP_QUERY_MAX_CHARS = 120;
const STEP_BADGE_MAX_CHARS = 24;
const STEP_CHIP_MAX_CHARS = 40;
const SUMMARY_MAX_CHARS = 200;
const SOURCE_TITLE_MAX_CHARS = 300;
const SOURCE_HOSTNAME_MAX_CHARS = 255;
const SOURCE_URL_MAX_CHARS = 2048;
const SOURCE_FALLBACK_LABEL_MAX_CHARS = 8;
const MAX_SOURCE_LINK_DEPTH = 9;

const STEP_ID_PATTERN = /^[A-Za-z0-9_-]{1,32}$/;
// 区切り（://）の直後からホスト部（userinfo を含む）の終わりまで。urlsplit の netloc に当たる。
// From just after "://" to the end of the authority (userinfo included); this is urlsplit's netloc.
const HTTP_URL_AUTHORITY_PATTERN = /^(https?):\/\/([^/?#]*)/i;

// 空白を 1 つにまとめ、上限（コードポイント数）を超えた分は末尾を「...」に置き換える。
// Collapse whitespace and replace anything past the limit (in code points) with a trailing "...".
function collapseText(value: unknown, maxChars: number): string {
  if (typeof value !== "string") return "";
  const text = value.split(/\s+/).filter(Boolean).join(" ");
  const characters = Array.from(text);
  if (characters.length <= maxChars) return text;
  return `${characters.slice(0, maxChars - 3).join("").trimEnd()}...`;
}

// リンクや画像の参照先として画面へ出せる HTTP(S) の URL か。ホストが空・認証情報つき・制御文字入りは不可。
// Whether the URL may be exposed as a link or image target: HTTP(S) with a host, no credentials, no control characters.
export function isSafeHttpUrl(url: unknown): url is string {
  if (typeof url !== "string" || !url || url.length > SOURCE_URL_MAX_CHARS) return false;
  if (/[\r\n\0]/.test(url)) return false;
  const match = HTTP_URL_AUTHORITY_PATTERN.exec(url.trim());
  if (!match || !match[2] || match[2].includes("@")) return false;
  try {
    new URL(url.trim());
  } catch {
    return false;
  }
  return true;
}

// サイト直下の favicon。出典が固有の favicon を持たないときの既定値。
// The favicon at the site root, the default for a source that carries none of its own.
function siteFaviconUrl(url: string): string {
  const match = HTTP_URL_AUTHORITY_PATTERN.exec(url.trim());
  return match ? `${match[1].toLowerCase()}://${match[2]}/favicon.ico` : "";
}

function normalizeSource(raw: unknown): AnswerTraceSource | null {
  const record = asRecord(raw);
  const url = typeof record.url === "string" ? record.url.trim() : "";
  if (!isSafeHttpUrl(url)) return null;
  const hostname = collapseText(record.hostname, SOURCE_HOSTNAME_MAX_CHARS);
  const title = collapseText(record.title, SOURCE_TITLE_MAX_CHARS) || url;
  const rawFavicon = typeof record.favicon_url === "string" ? record.favicon_url.trim() : "";
  const favicon_url = isSafeHttpUrl(rawFavicon) ? rawFavicon : siteFaviconUrl(url);
  const fallback_label =
    Array.from(collapseText(record.fallback_label, SOURCE_FALLBACK_LABEL_MAX_CHARS))[0] ||
    (Array.from((hostname || title).replace(/^www\./, ""))[0] ?? "").toUpperCase() ||
    "?";
  const rawDepth = record.link_depth;
  const depth = typeof rawDepth === "number" && Number.isInteger(rawDepth) ? rawDepth : 0;
  return {
    url,
    title,
    hostname,
    favicon_url,
    fallback_label,
    link_depth: Math.max(0, Math.min(depth, MAX_SOURCE_LINK_DEPTH)),
    linked_from: collapseText(record.linked_from, SOURCE_HOSTNAME_MAX_CHARS),
  };
}

function normalizeStep(raw: unknown): AnswerTraceStep | null {
  const record = asRecord(raw);
  const title = collapseText(record.title, STEP_TITLE_MAX_CHARS);
  if (!title) return null;
  const rawChips = Array.isArray(record.chips) ? record.chips : [];
  const rawSources = Array.isArray(record.sources) ? record.sources : [];
  const kind = typeof record.kind === "string" && STEP_KINDS.has(record.kind) ? record.kind : DEFAULT_STEP_KIND;
  const status =
    typeof record.status === "string" && STEP_STATUSES.has(record.status) ? record.status : DEFAULT_STEP_STATUS;
  return {
    id: typeof record.id === "string" ? record.id : "",
    kind: kind as AnswerTraceStepKind,
    status: status as AnswerTraceStepStatus,
    title,
    detail: collapseText(record.detail, STEP_DETAIL_MAX_CHARS),
    query: collapseText(record.query, STEP_QUERY_MAX_CHARS),
    badge: collapseText(record.badge, STEP_BADGE_MAX_CHARS),
    chips: rawChips
      .map((chip) => collapseText(chip, STEP_CHIP_MAX_CHARS))
      .filter(Boolean)
      .slice(0, MAX_STEP_CHIPS),
    sources: rawSources
      .map(normalizeSource)
      .filter((source): source is AnswerTraceSource => source !== null)
      .slice(0, MAX_STEP_SOURCES),
  };
}

// 実行記録を契約どおりの形へ正規化する。ステップが 1 つも残らなければ null。
// 上限を超えた分は切り詰め、形の合わない要素は捨てる。ステップ ID は回答内で一意にする（React の key と開閉状態の持ち主になるため）。
// 使える ID（形が合い、前のステップと重複しない）は先にすべて確保し、欠けている・不正・重複している ID だけを
// s1, s2, … の未使用の最小の番号で振り直す。振り直した ID が後ろのステップの元の ID とぶつからないようにするため。
// Normalize an execution record to the contract; null when no step survives. Anything over a limit is
// truncated and malformed items are dropped. Step ids are unique within the answer (the id is the React key
// that owns the open state). Usable ids (well-formed and not repeating an earlier step's) are all reserved
// first, and only a missing, malformed or duplicate id is reassigned to the smallest unused s1, s2, ...
// so a reassigned id can never collide with one a later step already has.
export function normalizeAnswerTrace(raw: unknown): AnswerTraceV1 | null {
  const record = asRecord(raw);
  if (record.version !== ANSWER_TRACE_VERSION) return null;
  const rawSteps = Array.isArray(record.steps) ? record.steps.slice(0, MAX_STEPS) : [];
  const steps = rawSteps.map(normalizeStep).filter((step): step is AnswerTraceStep => step !== null);
  if (steps.length === 0) return null;

  const reservedIds = new Set<string>();
  const keepsId = steps.map((step) => {
    const usable = STEP_ID_PATTERN.test(step.id) && !reservedIds.has(step.id);
    if (usable) reservedIds.add(step.id);
    return usable;
  });
  let nextNumber = 1;
  const uniqueSteps = steps.map((step, index) => {
    if (keepsId[index]) return step;
    while (reservedIds.has(`s${nextNumber}`)) nextNumber += 1;
    const id = `s${nextNumber}`;
    reservedIds.add(id);
    return { ...step, id };
  });
  return {
    version: ANSWER_TRACE_VERSION,
    summary: collapseText(record.summary, SUMMARY_MAX_CHARS),
    steps: uniqueSteps,
  };
}

// 実行記録のパーツ（構造化・旧形式のどちらか）か。
// Whether the part is an execution record, structured or legacy.
export function isAnswerTracePart(part: ChatMessagePart): boolean {
  return part.type === "answer_trace" || part.type === "legacy_answer_trace";
}

// 同じ内容の実行記録か。同じスナップショットの再送で画面を描き直さないための比較。
// Whether two execution records hold the same content, so a resent snapshot does not redraw the screen.
export function isSameAnswerTrace(a: AnswerTraceV1 | null | undefined, b: AnswerTraceV1 | null | undefined): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}

// パーツ列の実行記録を trace で置き換えて先頭に置く。生成中は、サーバーのパーツ更新が実行記録を
// 知らないため、受信済みのスナップショットをここで毎回載せ直す。trace が無ければパーツ列をそのまま返す。
// Put trace at the head of the part list, replacing any execution record in it. While generating, the
// server's parts updates do not know the record, so the received snapshot is laid on again every time.
// Without a trace the part list is returned as it is.
export function withAnswerTracePart(
  parts: ChatMessagePart[] | undefined,
  trace: AnswerTraceV1 | null | undefined,
): ChatMessagePart[] | undefined {
  if (!trace) return parts;
  return [{ type: "answer_trace", trace }, ...(parts ?? []).filter((part) => !isAnswerTracePart(part))];
}
