import { useState, useRef, useEffect, type FormEvent } from "react";

import { readSessionJson, writeSessionJson } from "../../lib/utils";
import MarkdownContent from "../MarkdownContent";

type ActionStep = {
  action: "app_action" | "click" | "input" | "focus" | "scroll" | "navigate" | "select" | "check" | "wait";
  command?: string;
  args?: Record<string, unknown>;
  selector?: string;
  path?: string;
  value?: string;
  checked?: boolean;
  timeout_ms?: number;
  risk?: "low" | "medium" | "high";
  description: string;
};

type ActionPlan = {
  description: string;
  steps: ActionStep[];
};

type Message = {
  sender: "user" | "assistant";
  text: string;
  actionPlan?: ActionPlan;
  isError?: boolean;
};

type AiAgentSseEvent =
  | { type: "progress"; message: string }
  | { type: "done"; response: string; model: string }
  | { type: "action_plan"; description: string; steps: ActionStep[] }
  | { type: "error"; message: string; retryable?: boolean; retry_after?: number };

type VisibleElementSummary = {
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

type StepExecutionResult = {
  ok: boolean;
  message?: string;
  failedStepIndex?: number;
  pendingNavigation?: boolean;
};

type ExecutionProgress = {
  messageIndex: number;
  currentStepIndex: number | null;
  completedStepIndexes: number[];
};

const QUICK_PROMPTS = [
  "このサービスはどんなことができる？",
  "この画面の使い方を教えて",
  "マニュアルからメモの共有方法を探して",
  "プロンプト共有を開いてメール返信を検索して"
];

const PENDING_ACTION_STEPS_KEY = "globalAiAgent.pendingActionSteps";
const AI_AGENT_OPEN_STATE_KEY = "globalAiAgent.isOpen";
const MESSAGES_STORAGE_KEY = "globalAiAgent.messages";
const MESSAGES_TIMESTAMP_KEY = "globalAiAgent.messagesTimestamp";
const EXECUTED_STORAGE_KEY = "globalAiAgent.executedMessageIndexes";

const SESSION_EXPIRY_MS = 24 * 60 * 60 * 1000;
const MAX_SEND_MESSAGES = 20;
const MAX_DOM_LENGTH = 12_000;
const MAX_INPUT_LENGTH = 4_000;

function parseSseBlock(block: string): AiAgentSseEvent | null {
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

async function* readSseStream(response: Response): AsyncGenerator<AiAgentSseEvent> {
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

function isPersistedMessage(value: unknown): value is Pick<Message, "sender" | "text"> {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<Message>;
  return (
    (candidate.sender === "user" || candidate.sender === "assistant")
    && typeof candidate.text === "string"
  );
}

function readStoredMessages(): Message[] {
  const timestamp = readSessionJson<number>(MESSAGES_TIMESTAMP_KEY, 0);
  if (timestamp > 0 && Date.now() - timestamp > SESSION_EXPIRY_MS) {
    writeSessionJson(MESSAGES_STORAGE_KEY, []);
    writeSessionJson(EXECUTED_STORAGE_KEY, []);
    writeSessionJson(MESSAGES_TIMESTAMP_KEY, 0);
    return [];
  }
  const raw = readSessionJson<unknown>(MESSAGES_STORAGE_KEY, []);
  if (!Array.isArray(raw)) return [];
  return raw.filter(isPersistedMessage).map(({ sender, text }) => ({ sender, text }));
}

function readStoredExecutedIndexes(): number[] {
  const raw = readSessionJson<unknown>(EXECUTED_STORAGE_KEY, []);
  if (!Array.isArray(raw)) return [];
  return raw.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
}

function cssEscape(value: string) {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(value);
  }
  return value.replace(/["\\#.;:[\]()>+~*='|\s]/g, "\\$&");
}

function truncateForContext(value: string | null | undefined, maxLength = 80) {
  const normalized = (value || "").replace(/\s+/g, " ").trim();
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized;
}

function wait(ms = 180) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

async function waitForElement(selector: string, timeoutMs = 1200): Promise<StepExecutionResult> {
  const startedAt = Date.now();
  while (Date.now() - startedAt <= timeoutMs) {
    if (isVisibleElement(document.querySelector(selector))) {
      return { ok: true };
    }
    await wait(80);
  }
  return { ok: false, message: `${selector} の表示を確認できませんでした。` };
}

function isActionStep(value: unknown): value is ActionStep {
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
  ) && typeof step.description === "string";
}

function readPendingActionSteps() {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.sessionStorage.getItem(PENDING_ACTION_STEPS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isActionStep) : [];
  } catch {
    return [];
  }
}

function writePendingActionSteps(steps: ActionStep[]) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(PENDING_ACTION_STEPS_KEY, JSON.stringify(steps));
    window.sessionStorage.setItem(AI_AGENT_OPEN_STATE_KEY, JSON.stringify(true));
  } catch {
    // ignore storage failures
  }
}

function clearPendingActionSteps() {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(PENDING_ACTION_STEPS_KEY);
  } catch {
    // ignore storage failures
  }
}

function getStepNavigationPath(step: ActionStep) {
  if (step.action === "navigate") return step.path || "";
  if (step.action === "app_action" && step.command === "navigation.openPage") {
    return getArg(step.args, "path");
  }
  return "";
}

function getArg(args: Record<string, unknown> | undefined, key: string) {
  const value = args?.[key];
  return typeof value === "string" ? value : "";
}

function getElement<T extends HTMLElement = HTMLElement>(selector: string): T | null {
  const element = document.querySelector(selector);
  return element instanceof HTMLElement ? element as T : null;
}

function isVisibleElement(element: Element | null) {
  if (!(element instanceof HTMLElement)) return false;
  const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
}

function buildElementSelector(element: Element): string | null {
  const id = element.getAttribute("id");
  if (id) return `#${cssEscape(id)}`;

  for (const attr of ["data-testid", "data-test", "data-section", "aria-label", "name"]) {
    const value = element.getAttribute(attr);
    if (value) return `${element.tagName.toLowerCase()}[${attr}="${cssEscape(value)}"]`;
  }

  const classNames = Array.from(element.classList).filter(Boolean).slice(0, 2);
  if (classNames.length > 0) {
    return `${element.tagName.toLowerCase()}.${classNames.map(cssEscape).join(".")}`;
  }

  return null;
}

function isVisibleActionableElement(element: Element) {
  if (element.closest(".global-ai-agent-modal")) return false;
  if (!(element instanceof HTMLElement)) return false;
  if (element.hidden || element.getAttribute("aria-hidden") === "true") return false;
  const rect = element.getBoundingClientRect();
  if (rect.width < 2 || rect.height < 2) return false;
  const style = window.getComputedStyle(element);
  return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) !== 0;
}

function collectVisiblePageDom() {
  if (typeof document === "undefined") return "";
  const elements = Array.from(
    document.querySelectorAll(
      "button, input, textarea, select, a[href], [role='button'], [role='tab'], [data-section], [data-category]"
    )
  ).filter(isVisibleActionableElement).slice(0, 80);

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
    summaries.push({
      selector,
      tag: element.tagName.toLowerCase(),
      text: truncateForContext(element.textContent),
      ariaLabel: truncateForContext(element.getAttribute("aria-label")),
      placeholder: truncateForContext(input?.placeholder),
      value: truncateForContext(input?.value ?? select?.value, 60),
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

function setNativeValue(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
  if (descriptor?.set) {
    descriptor.set.call(el, value);
  } else {
    el.value = value;
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function setInputValue(selector: string, value: string): StepExecutionResult {
  const el = getElement<HTMLInputElement | HTMLTextAreaElement>(selector);
  if (!(el instanceof HTMLInputElement) && !(el instanceof HTMLTextAreaElement)) {
    return { ok: false, message: `${selector} の入力欄が見つかりませんでした。` };
  }
  setNativeValue(el, value);
  return { ok: el.value === value, message: el.value === value ? undefined : `${selector} に入力値を反映できませんでした。` };
}

function setSelectValue(selector: string, value: string): StepExecutionResult {
  const el = getElement<HTMLSelectElement>(selector);
  if (!(el instanceof HTMLSelectElement)) {
    return { ok: false, message: `${selector} の選択欄が見つかりませんでした。` };
  }
  el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: el.value === value, message: el.value === value ? undefined : `${selector} に選択値を反映できませんでした。` };
}

function setCheckedValue(selector: string, checked: boolean): StepExecutionResult {
  const el = getElement<HTMLInputElement>(selector);
  if (!(el instanceof HTMLInputElement) || !/^(checkbox|radio)$/.test(el.type)) {
    return { ok: false, message: `${selector} のチェック項目が見つかりませんでした。` };
  }
  el.checked = checked;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: el.checked === checked, message: el.checked === checked ? undefined : `${selector} のチェック状態を反映できませんでした。` };
}

function clickElement(selector: string): StepExecutionResult {
  const el = getElement(selector);
  if (!el) return { ok: false, message: `${selector} が見つかりませんでした。` };
  if ((el as HTMLButtonElement).disabled) return { ok: false, message: `${selector} は現在無効です。` };
  el.click();
  return { ok: true };
}

function scrollElement(selector: string): StepExecutionResult {
  const el = getElement(selector);
  if (!el) return { ok: false, message: `${selector} が見つかりませんでした。` };
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  return { ok: true };
}

function executeAppAction(step: ActionStep): StepExecutionResult {
  const command = step.command || "";
  const args = step.args || {};

  if (command === "navigation.openPage") {
    const path = getArg(args, "path");
    if (!path.startsWith("/")) return { ok: false, message: "移動先パスが不正です。" };
    if (path === window.location.pathname) return { ok: true };
    window.location.href = path;
    return { ok: true };
  }

  if (command === "chat.fillSetupMessage") {
    return setInputValue("#setup-info", getArg(args, "text"));
  }
  if (command === "chat.sendSetupMessage") {
    return clickElement(".setup-send-btn");
  }
  if (command === "chat.openPromptComposer") {
    return clickElement("#openNewPromptModal");
  }
  if (command === "chat.toggleTaskOrder") {
    return clickElement("#edit-task-order-btn");
  }
  if (command === "chat.showChatHistory") {
    return clickElement("#access-chat-btn");
  }

  if (command === "prompt.search") {
    const inputResult = setInputValue("#searchInput", getArg(args, "query"));
    if (!inputResult.ok) return inputResult;
    return clickElement("#searchButton");
  }
  if (command === "prompt.openComposer") {
    return clickElement("#heroOpenPostModal");
  }
  if (command === "prompt.openLogin") {
    return clickElement("#login-btn");
  }
  if (command === "prompt.scrollResults") {
    return scrollElement("#prompt-feed-section");
  }

  if (command === "settings.openSection") {
    const section = getArg(args, "section");
    if (!/^(profile|appearance|prompts|prompt-list|notifications|security)$/.test(section)) {
      return { ok: false, message: "設定セクションの指定が不正です。" };
    }
    return clickElement(`[data-section="${cssEscape(section)}"]`);
  }

  if (command === "memo.fillForm") {
    const fieldMap: Record<string, string> = {
      input_content: "[name='input_content']",
      ai_response: "[name='ai_response']",
      title: "[name='title']",
      tags: "[name='tags']",
    };
    for (const [key, selector] of Object.entries(fieldMap)) {
      const value = getArg(args, key);
      if (!value) continue;
      const result = setInputValue(selector, value);
      if (!result.ok) return result;
    }
    return { ok: true };
  }
  if (command === "memo.save") {
    return clickElement("button[type='submit']");
  }

  if (command === "auth.fillEmail") {
    return setInputValue("#email", getArg(args, "email"));
  }
  if (command === "auth.startGoogleLogin") {
    return clickElement("#googleAuthBtn");
  }
  if (command === "auth.sendEmailCode") {
    return clickElement(".submit-btn");
  }

  return { ok: false, message: `未対応の操作コマンドです: ${command}` };
}

async function verifyStep(step: ActionStep): Promise<StepExecutionResult> {
  await wait();

  if (step.action === "app_action") {
    if (step.command === "chat.openPromptComposer") {
      return { ok: isVisibleElement(document.querySelector("#newPromptModal")), message: "新規プロンプト作成画面を確認できませんでした。" };
    }
    if (step.command === "prompt.openComposer") {
      return { ok: isVisibleElement(document.querySelector("#postModal")), message: "プロンプト投稿画面を確認できませんでした。" };
    }
    if (step.command === "settings.openSection") {
      const section = getArg(step.args, "section");
      const active = document.querySelector(`[data-section="${cssEscape(section)}"].active, [data-section="${cssEscape(section)}"][aria-current='page']`);
      return { ok: Boolean(active), message: "設定セクションの切り替えを確認できませんでした。" };
    }
    if (step.command === "prompt.search") {
      const input = getElement<HTMLInputElement>("#searchInput");
      const query = getArg(step.args, "query");
      return { ok: !query || input?.value === query, message: "検索語の入力を確認できませんでした。" };
    }
    return { ok: true };
  }

  if (step.action === "input" && step.selector) {
    const el = getElement<HTMLInputElement | HTMLTextAreaElement>(step.selector);
    const expected = step.value ?? "";
    return { ok: Boolean(el && "value" in el && el.value === expected), message: `${step.selector} の入力結果を確認できませんでした。` };
  }
  if (step.action === "select" && step.selector) {
    const el = getElement<HTMLSelectElement>(step.selector);
    const expected = step.value ?? "";
    return { ok: Boolean(el && el.value === expected), message: `${step.selector} の選択結果を確認できませんでした。` };
  }
  if (step.action === "check" && step.selector) {
    const el = getElement<HTMLInputElement>(step.selector);
    const expected = step.checked ?? true;
    return { ok: Boolean(el && el.checked === expected), message: `${step.selector} のチェック状態を確認できませんでした。` };
  }
  if (step.action === "wait") {
    if (!step.selector) return { ok: true };
    return { ok: isVisibleElement(document.querySelector(step.selector)), message: `${step.selector} の表示を確認できませんでした。` };
  }
  if (step.action === "focus" && step.selector) {
    return { ok: document.activeElement === document.querySelector(step.selector), message: `${step.selector} のフォーカスを確認できませんでした。` };
  }
  if ((step.action === "click" || step.action === "scroll") && step.selector) {
    return { ok: Boolean(document.querySelector(step.selector)), message: `${step.selector} が見つかりませんでした。` };
  }
  return { ok: true };
}

async function executeActionStep(step: ActionStep): Promise<StepExecutionResult> {
  if (step.risk === "high" && !window.confirm("この操作は取り消しにくい可能性があります。実行しますか？")) {
    return { ok: false, message: "ユーザー確認で操作を中止しました。" };
  }

  let result: StepExecutionResult;
  if (step.action === "app_action") {
    result = executeAppAction(step);
  } else if (step.action === "navigate") {
    if (!step.path?.startsWith("/")) return { ok: false, message: "移動先パスが不正です。" };
    if (step.path === window.location.pathname) return { ok: true };
    window.location.href = step.path;
    return { ok: true };
  } else if (step.action === "input") {
    if (!step.selector) return { ok: false, message: "入力先が指定されていません。" };
    result = setInputValue(step.selector, step.value ?? "");
  } else if (step.action === "select") {
    if (!step.selector) return { ok: false, message: "選択先が指定されていません。" };
    result = setSelectValue(step.selector, step.value ?? "");
  } else if (step.action === "check") {
    if (!step.selector) return { ok: false, message: "チェック対象が指定されていません。" };
    result = setCheckedValue(step.selector, step.checked ?? true);
  } else if (step.action === "wait") {
    const timeoutMs = Math.max(0, Math.min(step.timeout_ms ?? 1200, 5000));
    result = step.selector ? await waitForElement(step.selector, timeoutMs) : { ok: true };
    if (!step.selector && timeoutMs > 0) await wait(timeoutMs);
  } else if (step.action === "click") {
    if (!step.selector) return { ok: false, message: "クリック先が指定されていません。" };
    result = clickElement(step.selector);
  } else if (step.action === "focus") {
    if (!step.selector) return { ok: false, message: "フォーカス先が指定されていません。" };
    const el = getElement(step.selector);
    if (!el) return { ok: false, message: `${step.selector} が見つかりませんでした。` };
    el.focus();
    result = { ok: true };
  } else {
    if (!step.selector) return { ok: false, message: "スクロール先が指定されていません。" };
    result = scrollElement(step.selector);
  }

  if (!result.ok) return result;
  return verifyStep(step);
}

async function executeActionSteps(
  steps: ActionStep[],
  onStepProgress?: (stepIndex: number, status: "current" | "complete") => void,
): Promise<StepExecutionResult> {
  for (const [stepIndex, step] of steps.entries()) {
    const remaining = steps.slice(stepIndex + 1);
    const navigationPath = getStepNavigationPath(step);
    const willNavigate = Boolean(navigationPath) && navigationPath !== window.location.pathname;

    if (remaining.length) {
      writePendingActionSteps(remaining);
    } else {
      clearPendingActionSteps();
    }

    onStepProgress?.(stepIndex, "current");
    const result = await executeActionStep(step);
    if (!result.ok) {
      clearPendingActionSteps();
      return { ...result, failedStepIndex: stepIndex };
    }

    if (willNavigate && remaining.length) {
      return { ok: true, pendingNavigation: true };
    }

    onStepProgress?.(stepIndex, "complete");
  }

  clearPendingActionSteps();
  return { ok: true };
}

const ACTION_LABELS: Record<ActionStep["action"], string> = {
  app_action: "操作",
  click: "クリック",
  input: "入力",
  focus: "フォーカス",
  scroll: "スクロール",
  navigate: "移動",
  select: "選択",
  check: "チェック",
  wait: "待機",
};

const INITIAL_PROGRESS_MESSAGE = "依頼を送信しています...";

export function MiniChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [progressSteps, setProgressSteps] = useState<string[]>([]);
  const [executingIdx, setExecutingIdx] = useState<number | null>(null);
  const [executionProgress, setExecutionProgress] = useState<ExecutionProgress | null>(null);
  const [executedSet, setExecutedSet] = useState<Set<number>>(new Set());
  const [hydrated, setHydrated] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const trimmedInput = input.trim();
  const currentProgressText = statusText ?? progressSteps[progressSteps.length - 1] ?? null;

  // Keep ref in sync for stale-closure-safe access in async handlers
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const appendProgressStep = (message: string) => {
    setStatusText(message);
    setProgressSteps((prev) => (
      prev[prev.length - 1] === message ? prev : [...prev, message]
    ));
  };

  const requestAiAgentMessage = async (
    nextMessages: Message[],
    signal: AbortSignal,
  ): Promise<Message> => {
    const response = await fetch("/api/ai-agent", {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: nextMessages.slice(-MAX_SEND_MESSAGES).map((m) => ({ role: m.sender, content: m.text })),
        current_page: typeof window !== "undefined" ? window.location.pathname : null,
        current_dom: collectVisiblePageDom().slice(0, MAX_DOM_LENGTH),
      }),
    });

    if (!response.ok) {
      throw new Error(`サーバーエラー (${response.status})`);
    }

    let assistantText = "応答を取得できませんでした。もう一度試してください。";
    let actionPlan: ActionPlan | undefined;

    for await (const event of readSseStream(response)) {
      if (event.type === "progress") {
        appendProgressStep(event.message);
      } else if (event.type === "done") {
        assistantText = event.response.trim() || assistantText;
        break;
      } else if (event.type === "action_plan") {
        assistantText = event.description;
        actionPlan = { description: event.description, steps: event.steps };
        break;
      } else if (event.type === "error") {
        assistantText = event.message;
        break;
      }
    }

    return { sender: "assistant", text: assistantText, actionPlan };
  };

  const handleSend = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    if (!trimmedInput || isGenerating) return;

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const userMessage: Message = { sender: "user", text: trimmedInput };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setInput("");
    setIsGenerating(true);
    setStatusText(INITIAL_PROGRESS_MESSAGE);
    setProgressSteps([INITIAL_PROGRESS_MESSAGE]);

    try {
      const assistantMessage = await requestAiAgentMessage(nextMessages, controller.signal);
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setMessages((prev) => [
        ...prev,
        {
          sender: "assistant",
          text: error instanceof Error ? error.message : "AIエージェントの応答生成に失敗しました。",
          isError: true,
        },
      ]);
    } finally {
      abortControllerRef.current = null;
      setIsGenerating(false);
      setStatusText(null);
      setProgressSteps([]);
    }
  };

  const handleStop = () => {
    abortControllerRef.current?.abort();
  };

  const handleRetry = async (errorMsgIndex: number) => {
    const messagesBeforeError = messages.slice(0, errorMsgIndex);
    setMessages(messagesBeforeError);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsGenerating(true);
    setStatusText(INITIAL_PROGRESS_MESSAGE);
    setProgressSteps([INITIAL_PROGRESS_MESSAGE]);

    try {
      const assistantMessage = await requestAiAgentMessage(messagesBeforeError, controller.signal);
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setMessages((prev) => [
        ...prev,
        {
          sender: "assistant",
          text: error instanceof Error ? error.message : "AIエージェントの応答生成に失敗しました。",
          isError: true,
        },
      ]);
    } finally {
      abortControllerRef.current = null;
      setIsGenerating(false);
      setStatusText(null);
      setProgressSteps([]);
    }
  };

  const handleCopy = async (text: string, index: number) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex((prev) => (prev === index ? null : prev)), 2000);
    } catch {
      // clipboard API unavailable
    }
  };

  const handleExecuteActions = async (steps: ActionStep[], msgIdx: number) => {
    setExecutingIdx(msgIdx);
    setExecutionProgress({
      messageIndex: msgIdx,
      currentStepIndex: null,
      completedStepIndexes: [],
    });
    try {
      const result = await executeActionSteps(steps, (stepIndex, status) => {
        setExecutionProgress((current) => {
          if (!current || current.messageIndex !== msgIdx) {
            return {
              messageIndex: msgIdx,
              currentStepIndex: status === "current" ? stepIndex : null,
              completedStepIndexes: status === "complete" ? [stepIndex] : [],
            };
          }
          const completed = new Set(current.completedStepIndexes);
          if (status === "complete") completed.add(stepIndex);
          return {
            messageIndex: msgIdx,
            currentStepIndex: status === "current"
              ? stepIndex
              : current.currentStepIndex === stepIndex
                ? null
                : current.currentStepIndex,
            completedStepIndexes: Array.from(completed).sort((a, b) => a - b),
          };
        });
      });
      if (result.ok) {
        setExecutedSet((prev) => new Set([...prev, msgIdx]));
        if (result.pendingNavigation) {
          const merged = Array.from(new Set([...readStoredExecutedIndexes(), msgIdx]));
          writeSessionJson(EXECUTED_STORAGE_KEY, merged);
        }
      } else {
        const failureText = result.message || "画面状態を確認できませんでした。";
        const failedStepText = typeof result.failedStepIndex === "number"
          ? `失敗ステップ: ${result.failedStepIndex + 1}`
          : "";
        const replanPrompt = [
          "前回の操作計画は実行中に失敗しました。",
          failedStepText,
          `失敗理由: ${failureText}`,
          "現在の画面DOMを再観測し、成功確認しやすい型付きアクションAPIを優先して、実行可能な操作計画だけを作り直してください。",
        ].filter(Boolean).join("\n");

        const controller = new AbortController();
        abortControllerRef.current = controller;
        setIsGenerating(true);
        setStatusText("画面を再確認しています...");
        setProgressSteps(["画面を再確認しています..."]);

        try {
          const replanMessage = await requestAiAgentMessage(
            [
              ...messagesRef.current,
              { sender: "user", text: replanPrompt },
            ],
            controller.signal,
          );
          setMessages((prev) => [
            ...prev,
            {
              sender: "assistant",
              text: `操作を途中で停止しました。${failureText}`,
            },
            replanMessage,
          ]);
        } catch (replanError) {
          if (!(replanError instanceof DOMException && replanError.name === "AbortError")) {
            setMessages((prev) => [
              ...prev,
              {
                sender: "assistant",
                text: replanError instanceof Error ? replanError.message : "操作の再計画に失敗しました。",
                isError: true,
              },
            ]);
          }
        } finally {
          abortControllerRef.current = null;
          setIsGenerating(false);
          setStatusText(null);
          setProgressSteps([]);
        }
      }
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          sender: "assistant",
          text: error instanceof Error ? error.message : "操作の実行に失敗しました。",
          isError: true,
        },
      ]);
    } finally {
      setExecutingIdx(null);
      setExecutionProgress(null);
    }
  };

  useEffect(() => {
    const storedMessages = readStoredMessages();
    const storedExecuted = readStoredExecutedIndexes();
    if (storedMessages.length) setMessages(storedMessages);
    if (storedExecuted.length) setExecutedSet(new Set(storedExecuted));
    setHydrated(true);

    const pendingSteps = readPendingActionSteps();
    if (!pendingSteps.length) return undefined;
    clearPendingActionSteps();

    let timer: number | undefined;
    setMessages((prev) => {
      const messageIndex = prev.length;
      timer = window.setTimeout(() => {
        void handleExecuteActions(pendingSteps, messageIndex);
      }, 360);
      return [
        ...prev,
        {
          sender: "assistant",
          text: "移動後の残り操作を続けます。",
          actionPlan: {
            description: "移動後の残り操作を続けます。",
            steps: pendingSteps,
          },
        },
      ];
    });

    return () => {
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  // Persist messages without actionPlan/isError (not restorable after reload)
  useEffect(() => {
    if (!hydrated) return;
    writeSessionJson(
      MESSAGES_STORAGE_KEY,
      messages.map(({ sender, text }) => ({ sender, text })),
    );
    writeSessionJson(MESSAGES_TIMESTAMP_KEY, messages.length > 0 ? Date.now() : 0);
  }, [hydrated, messages]);

  useEffect(() => {
    if (!hydrated) return;
    writeSessionJson(EXECUTED_STORAGE_KEY, Array.from(executedSet));
  }, [hydrated, executedSet]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isGenerating, statusText, progressSteps.length]);

  return (
    <div className="mini-chat-container">
      <div className="mini-chat-messages" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="mini-chat-placeholder">
            <span className="mini-chat-robot-icon" aria-hidden="true">
              <i className="bi bi-stars"></i>
            </span>
            <strong>操作支援エージェント</strong>
            <p>画面の使い方、次の操作、入力内容の整理を短い会話で進められます。</p>
            <div className="mini-chat-suggestions" aria-label="入力候補">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  className="mini-chat-suggestion"
                  onClick={() => setInput(prompt)}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={`${msg.sender}-${i}`} className={`mini-chat-message mini-chat-message--${msg.sender}`}>
            <span className="mini-chat-avatar" aria-hidden="true">
              <i className={`bi ${msg.sender === "user" ? "bi-person" : "bi-stars"}`}></i>
            </span>
            <div className={`mini-chat-text-wrapper${msg.isError ? " mini-chat-text-wrapper--error" : ""}`}>
              {msg.sender === "assistant" ? (
                <MarkdownContent text={msg.text} className="mini-chat-text mini-chat-markdown" />
              ) : (
                <div className="mini-chat-text">{msg.text}</div>
              )}
              {msg.actionPlan && (
                <div className="mini-chat-action-plan">
                  <ol className="mini-chat-action-steps">
                    {msg.actionPlan.steps.map((step, si) => (
                      <li
                        key={si}
                        className={`mini-chat-action-step ${
                          executionProgress?.messageIndex === i && executionProgress.currentStepIndex === si
                            ? "is-current"
                            : executionProgress?.messageIndex === i && executionProgress.completedStepIndexes.includes(si)
                              ? "is-complete"
                              : executedSet.has(i)
                                ? "is-complete"
                                : ""
                        }`.trim()}
                        aria-current={
                          executionProgress?.messageIndex === i && executionProgress.currentStepIndex === si
                            ? "step"
                            : undefined
                        }
                      >
                        <span className={`mini-chat-action-badge mini-chat-action-badge--${step.action}`}>
                          {ACTION_LABELS[step.action]}
                        </span>
                        <span className="mini-chat-action-index">{si + 1}</span>
                        {step.description}
                      </li>
                    ))}
                  </ol>
                  <button
                    type="button"
                    className="mini-chat-execute-btn"
                    onClick={() => handleExecuteActions(msg.actionPlan!.steps, i)}
                    disabled={executingIdx === i || executedSet.has(i)}
                    aria-label="操作を実行"
                  >
                    {executingIdx === i ? (
                      <><i className="bi bi-three-dots"></i> 実行中...</>
                    ) : executedSet.has(i) ? (
                      <><i className="bi bi-check2"></i> 実行済み</>
                    ) : (
                      <><i className="bi bi-play-fill"></i> 実行</>
                    )}
                  </button>
                </div>
              )}
              {msg.sender === "assistant" && (
                <div className="mini-chat-message-toolbar">
                  <button
                    type="button"
                    className="mini-chat-copy-btn"
                    onClick={() => void handleCopy(msg.text, i)}
                    aria-label="回答をコピー"
                  >
                    <i className={`bi ${copiedIndex === i ? "bi-check2" : "bi-copy"}`}></i>
                    {copiedIndex === i ? "コピー済み" : "コピー"}
                  </button>
                  {msg.isError && (
                    <button
                      type="button"
                      className="mini-chat-retry-btn"
                      onClick={() => void handleRetry(i)}
                      disabled={isGenerating}
                      aria-label="再試行"
                    >
                      <i className="bi bi-arrow-clockwise"></i>
                      再試行
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {isGenerating ? (
          <div className="mini-chat-message mini-chat-message--assistant mini-chat-message--typing" aria-live="polite">
            <span className="mini-chat-avatar" aria-hidden="true">
              <i className="bi bi-stars"></i>
            </span>
            <div className="mini-chat-text-wrapper">
              {currentProgressText ? (
                <div className="mini-chat-progress" role="status">
                  <span className="mini-chat-status-text">{currentProgressText}</span>
                  {progressSteps.length > 0 ? (
                    <ol className="mini-chat-progress-list" aria-label="AIエージェントの進捗">
                      {progressSteps.map((step, stepIndex) => (
                        <li
                          key={`${step}-${stepIndex}`}
                          className={`mini-chat-progress-step ${
                            stepIndex === progressSteps.length - 1 ? "is-current" : "is-complete"
                          }`}
                        >
                          {step}
                        </li>
                      ))}
                    </ol>
                  ) : null}
                </div>
              ) : (
                <>
                  <span className="mini-chat-typing-dot"></span>
                  <span className="mini-chat-typing-dot"></span>
                  <span className="mini-chat-typing-dot"></span>
                </>
              )}
            </div>
          </div>
        ) : null}
      </div>
      <form className="mini-chat-input-area" onSubmit={handleSend}>
        <div className="mini-chat-input-wrapper">
          <input
            type="text"
            className="mini-chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="この画面でやりたいことを相談する"
            aria-label="AIサポートへのメッセージ"
            maxLength={MAX_INPUT_LENGTH}
            disabled={isGenerating}
          />
          {isGenerating ? (
            <button
              type="button"
              className="mini-chat-stop-btn"
              onClick={handleStop}
              aria-label="生成を停止"
            >
              <i className="bi bi-stop-fill"></i>
            </button>
          ) : (
            <button
              type="submit"
              className="mini-chat-send-btn"
              disabled={!trimmedInput}
              aria-label="送信"
            >
              <i className="bi bi-arrow-up-short"></i>
            </button>
          )}
        </div>
        <button
          type="button"
          className="mini-chat-action-btn"
          onClick={() => {
            setMessages([]);
            setExecutedSet(new Set());
          }}
          disabled={!messages.length || isGenerating}
          aria-label="会話をクリア"
        >
          <i className="bi bi-trash3"></i>
        </button>
      </form>
    </div>
  );
}
