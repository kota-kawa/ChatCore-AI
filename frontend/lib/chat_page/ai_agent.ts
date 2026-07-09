export type ActionStep = {
  action: "app_action" | "click" | "input" | "focus" | "scroll" | "navigate" | "select" | "check" | "wait" | "memo_edit";
  command?: string;
  args?: Record<string, unknown>;
  selector?: string;
  path?: string;
  value?: string;
  checked?: boolean;
  timeout_ms?: number;
  risk?: "low" | "medium" | "high";
  description: string;
  /** memo_edit: 編集後のメモ本文全文 / full replacement body for the open memo */
  content?: string;
  /** memo_edit: 新しいタイトル（変更時のみ） / new memo title when the edit renames it */
  title?: string;
};

export type ActionPlan = {
  description: string;
  steps: ActionStep[];
};

export type Message = {
  id: string;
  sender: "user" | "assistant";
  text: string;
  actionPlan?: ActionPlan;
  isError?: boolean;
};

export type AiAgentSseEvent =
  | { type: "progress"; message: string }
  | { type: "done"; response: string; model: string }
  | { type: "action_plan"; description: string; steps: ActionStep[] }
  | { type: "error"; message: string; retryable?: boolean; retry_after?: number };

export type VisibleElementSummary = {
  selector: string;
  tag: string;
  text?: string;
  ariaLabel?: string;
  placeholder?: string;
  value?: string;
  inputType?: string;
  checked?: boolean;
  disabled?: boolean;
  options?: string;
  href?: string;
  role?: string;
};

export type StepExecutionResult = {
  ok: boolean;
  message?: string;
  failedStepIndex?: number;
  /** A full page reload was triggered; remaining steps were persisted for resume. */
  pendingNavigation?: boolean;
  /**
   * Set when a step navigated. "client" means an in-place (Next router) navigation
   * that kept the agent mounted; "hard" means a full document reload is imminent.
   */
  navigation?: "client" | "hard";
  /** The destination pathname is now ready for the next step to act on. */
  navigatedTo?: string;
  /** The destination DOM no longer matches the plan; a fresh re-plan is needed. */
  needsReplan?: boolean;
};

type ErrorPayload = {
  error?: unknown;
  message?: unknown;
  retry_after?: unknown;
};

/**
 * AIエージェント用のメッセージIDを生成する
 * Create a message ID for the AI agent
 */
export function createAiAgentMessageId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * CSSセレクタ用に文字列をエスケープする
 * Escape a string for use in a CSS selector
 */
export function cssEscape(value: string) {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(value);
  }
  return value.replace(/["\\#.;:[\]()>+~*='|\s]/g, "\\$&");
}

/**
 * AIのコンテキスト長を節約するために文字列を切り詰める
 * Truncate a string to save context length for the AI
 */
export function truncateForContext(value: string | null | undefined, maxLength = 80) {
  const normalized = (value || "").replace(/\s+/g, " ").trim();
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized;
}

/**
 * 要素が画面上に表示されているかどうかを判定する
 * Check if the element is visible on the screen
 */
export function isVisibleElement(element: Element | null) {
  if (!(element instanceof HTMLElement)) return false;
  const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
}

/**
 * 安全な内部パスかどうかを検証する
 * Verify if the path is a safe internal path
 */
export function isSafeInternalPath(path: string | undefined): path is string {
  if (!path || !path.startsWith("/") || path.startsWith("//")) return false;
  if (/[\u0000-\u001f]/.test(path)) return false;
  return !/^\/[a-z][a-z0-9+.-]*:/i.test(path);
}

/** Collapse a pathname to a comparable form: lower-cased, query/hash stripped, no trailing slash. */
export function normalizePathname(pathname: string | undefined): string {
  if (!pathname) return "";
  const withoutQuery = pathname.split(/[?#]/, 1)[0];
  const lowered = withoutQuery.toLowerCase();
  if (lowered.length > 1 && lowered.endsWith("/")) {
    return lowered.replace(/\/+$/, "") || "/";
  }
  return lowered;
}

/**
 * Two internal pathnames refer to the same destination if they normalize equal,
 * or one is a path-segment prefix of the other (handles redirects that append a
 * sub-route, e.g. /settings -> /settings/profile).
 */
export function pathnamesMatch(expected: string | undefined, actual: string | undefined): boolean {
  const a = normalizePathname(expected);
  const b = normalizePathname(actual);
  if (!a || !b) return false;
  if (a === b) return true;
  const [shorter, longer] = a.length <= b.length ? [a, b] : [b, a];
  if (shorter === "/") return false;
  return longer.startsWith(`${shorter}/`);
}

// The only destinations the agent is allowed to navigate to: real, side-effect-free app
// pages from the capability catalog. This blocks navigation to mutating GET endpoints
// (e.g. /logout, /google-login) and anything outside the app.
export const NAVIGABLE_APP_ROUTES = [
  "/",
  "/prompt_share",
  "/prompt_share/manage",
  "/memo",
  "/settings",
  "/login",
];

export function isAllowedNavigationPath(path: string | undefined): boolean {
  if (!isSafeInternalPath(path)) return false;
  const target = normalizePathname(path);
  if (!target) return false;
  return NAVIGABLE_APP_ROUTES.some((route) => pathnamesMatch(route, target));
}

// Words that signal an irreversible / state-changing control. Used to force a confirmation
// before clicking such a control even when the model labelled the step low risk.
const DESTRUCTIVE_INTENT_PATTERN =
  /(削除|消去|破棄|取り消|退会|解約|購入|支払|決済|送信|投稿|保存|登録|ログアウト|サインアウト|delete|remove|destroy|discard|purchase|checkout|\bbuy\b|\bpay\b|submit|publish|sign[\s-]*out|log[\s-]*out)/i;

export function isDestructiveActionLabel(text: string | null | undefined): boolean {
  if (!text) return false;
  return DESTRUCTIVE_INTENT_PATTERN.test(text);
}

const SENSITIVE_AUTOCOMPLETE_PATTERN =
  /(password|current-password|new-password|one-time-code|cc-number|cc-csc|cc-exp|cc-name)/i;
const SENSITIVE_NAME_PATTERN = /(pass(word)?|secret|token|otp|cvv|card[\s_-]?number)/i;

/** Inputs whose value must never be sent to the LLM (passwords, hidden fields, payment data). */
export function isSensitiveValueElement(element: Element): boolean {
  if (!(element instanceof HTMLInputElement)) return false;
  if (element.type === "password" || element.type === "hidden") return true;
  if (SENSITIVE_AUTOCOMPLETE_PATTERN.test(element.getAttribute("autocomplete") || "")) return true;
  return SENSITIVE_NAME_PATTERN.test(element.getAttribute("name") || "");
}

const AUTH_PATHNAMES = new Set(["/login", "/register"]);

/** True when navigation landed on an auth gate it was not asked to open. */
export function isUnexpectedAuthRedirect(
  expectedPath: string | undefined,
  actualPathname: string | undefined,
): boolean {
  const actual = normalizePathname(actualPathname);
  if (!AUTH_PATHNAMES.has(actual)) return false;
  const expected = normalizePathname(expectedPath);
  return !AUTH_PATHNAMES.has(expected);
}

/**
 * 要素のセレクターを構築する
 * Build a CSS selector for an element
 */
function buildElementSelector(element: Element): string | null {
  const id = element.getAttribute("id");
  if (id) return `#${cssEscape(id)}`;

  for (const attr of ["data-agent-id", "data-testid", "data-test", "data-section", "aria-label", "name"]) {
    const value = element.getAttribute(attr);
    if (value) return `${element.tagName.toLowerCase()}[${attr}="${cssEscape(value)}"]`;
  }

  const classNames = Array.from(element.classList).filter(Boolean).slice(0, 2);
  if (classNames.length > 0) {
    return `${element.tagName.toLowerCase()}.${classNames.map(cssEscape).join(".")}`;
  }

  return null;
}

/**
 * 要素が操作可能かつ可視であるか判定する
 * Check if the element is actionable and visible
 */
function isVisibleActionableElement(element: Element) {
  // モーダル内の要素は除外
  // Exclude elements inside the global agent modal
  if (element.closest(".global-ai-agent-modal")) return false;
  if (!(element instanceof HTMLElement)) return false;
  if (element.hidden || element.getAttribute("aria-hidden") === "true") return false;
  const rect = element.getBoundingClientRect();
  if (rect.width < 2 || rect.height < 2) return false;
  const style = window.getComputedStyle(element);
  return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) !== 0;
}

export function collectVisiblePageDom() {
  if (typeof document === "undefined") return "";
  const elements = Array.from(
    document.querySelectorAll(
      "button, input, textarea, select, a[href], [role='button'], [role='tab'], [data-agent-id], [data-section], [data-category]"
    )
  ).filter(isVisibleActionableElement).slice(0, 100);

  const summaries: VisibleElementSummary[] = [];
  const seenSelectors = new Set<string>();

  for (const element of elements) {
    const selector = buildElementSelector(element);
    if (!selector || seenSelectors.has(selector)) continue;
    seenSelectors.add(selector);

    const input = element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement ? element : null;
    const select = element instanceof HTMLSelectElement ? element : null;
    const disabled = "disabled" in element && typeof element.disabled === "boolean"
      ? element.disabled
      : undefined;
    const sensitive = isSensitiveValueElement(element);
    summaries.push({
      selector,
      tag: element.tagName.toLowerCase(),
      text: truncateForContext(element.textContent),
      ariaLabel: truncateForContext(element.getAttribute("aria-label")),
      placeholder: truncateForContext(input?.placeholder),
      // Never transmit secrets/PII held in password, hidden, or payment fields.
      value: sensitive ? undefined : truncateForContext(input?.value ?? select?.value, 60),
      inputType: element instanceof HTMLInputElement ? element.type : undefined,
      checked: element instanceof HTMLInputElement && /^(checkbox|radio)$/.test(element.type)
        ? element.checked
        : undefined,
      disabled,
      options: select
        ? Array.from(select.options)
          .slice(0, 12)
          .map((option) => `${truncateForContext(option.textContent, 28)}=${truncateForContext(option.value, 28)}`)
          .join(", ")
        : undefined,
      href: truncateForContext(element instanceof HTMLAnchorElement ? element.getAttribute("href") : null),
      role: truncateForContext(element.getAttribute("role")),
    });
  }

  return summaries
    .map((item, index) => (
      `${index + 1}. selector=${item.selector}; tag=${item.tag}`
      + `${item.text ? `; text=${item.text}` : ""}`
      + `${item.ariaLabel ? `; aria-label=${item.ariaLabel}` : ""}`
      + `${item.placeholder ? `; placeholder=${item.placeholder}` : ""}`
      + `${item.value ? `; value=${item.value}` : ""}`
      + `${item.inputType ? `; input-type=${item.inputType}` : ""}`
      + `${typeof item.checked === "boolean" ? `; checked=${item.checked}` : ""}`
      + `${typeof item.disabled === "boolean" ? `; disabled=${item.disabled}` : ""}`
      + `${item.options ? `; options=${item.options}` : ""}`
      + `${item.href ? `; href=${item.href}` : ""}`
      + `${item.role ? `; role=${item.role}` : ""}`
    ))
    .join("\n");
}

export function isActionStep(value: unknown): value is ActionStep {
  if (!value || typeof value !== "object") return false;
  const step = value as Partial<ActionStep>;
  return (
    step.action === "app_action"
    || step.action === "click"
    || step.action === "input"
    || step.action === "focus"
    || step.action === "scroll"
    || step.action === "navigate"
    || step.action === "select"
    || step.action === "check"
    || step.action === "wait"
    || step.action === "memo_edit"
  ) && typeof step.description === "string";
}

/**
 * SSEブロックをパースしてイベントに変換する
 * Parse an SSE block into an event
 */
export function parseSseBlock(block: string): AiAgentSseEvent | null {
  if (!block.trim()) return null;
  let eventType = "message";
  const dataLines: string[] = [];

  for (const rawLine of block.split(/\r?\n/)) {
    const line = rawLine.trimEnd();
    if (line.startsWith("event:")) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (!dataLines.length) return null;
  try {
    const parsed = JSON.parse(dataLines.join("\n"));
    return { type: eventType, ...parsed } as AiAgentSseEvent;
  } catch {
    return null;
  }
}

/**
 * SSEストリームを非同期ジェネレーターとして読み込む
 * Read an SSE stream as an asynchronous generator
 */
export async function* readSseStream(response: Response): AsyncGenerator<AiAgentSseEvent> {
  if (!response.body) throw new Error("レスポンスボディがありません。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";

    for (const block of blocks) {
      const event = parseSseBlock(block);
      if (event) yield event;
    }
  }

  buffer += decoder.decode();
  const trailingEvent = parseSseBlock(buffer);
  if (trailingEvent) yield trailingEvent;
}

/**
 * AIエージェントのHTTPエラーからエラーオブジェクトを生成する
 * Build an error object from an AI agent HTTP error response
 */
export async function buildAiAgentHttpError(response: Response): Promise<Error> {
  let payload: ErrorPayload | null = null;
  try {
    payload = await response.clone().json() as ErrorPayload;
  } catch {
    payload = null;
  }

  const baseMessage = typeof payload?.error === "string"
    ? payload.error
    : typeof payload?.message === "string"
      ? payload.message
      : `サーバーエラー (${response.status})`;
  const retryAfter = typeof payload?.retry_after === "number" && Number.isFinite(payload.retry_after)
    ? Math.ceil(payload.retry_after)
    : null;
  const suffix = retryAfter && retryAfter > 0 ? ` ${retryAfter}秒ほど待ってから再試行してください。` : "";
  return new Error(`${baseMessage}${suffix}`);
}
