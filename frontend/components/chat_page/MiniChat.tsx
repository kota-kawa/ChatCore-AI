import { useState, useRef, useEffect, type FormEvent } from "react";

import {
  buildAiAgentHttpError,
  collectVisiblePageDom,
  createAiAgentMessageId,
  cssEscape,
  isActionStep,
  isSafeInternalPath,
  isVisibleElement,
  readSseStream,
  type ActionPlan,
  type ActionStep,
  type Message,
  type StepExecutionResult,
} from "../../lib/chat_page/ai_agent";
import { readSessionJson, writeSessionJson } from "../../lib/utils";
import { showConfirmModal } from "../../scripts/core/alert_modal";
import MarkdownContent from "../MarkdownContent";

type ExecutionProgress = {
  messageId: string;
  currentStepIndex: number | null;
  completedStepIndexes: number[];
};

type PendingActionState = {
  steps: ActionStep[];
  expectedPath?: string;
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
const EXECUTED_STORAGE_KEY = "globalAiAgent.executedMessageIds";
const LEGACY_EXECUTED_STORAGE_KEY = "globalAiAgent.executedMessageIndexes";

const SESSION_EXPIRY_MS = 24 * 60 * 60 * 1000;
const PENDING_ACTION_EXPIRY_MS = 10 * 60 * 1000;
const MAX_SEND_MESSAGES = 20;
const MAX_DOM_LENGTH = 12_000;
const MAX_INPUT_LENGTH = 4_000;
const RESUME_READY_TIMEOUT_MS = 12_000;

function isPersistedMessage(value: unknown): value is Message {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<Message>;
  return (
    (candidate.id === undefined || typeof candidate.id === "string")
    &&
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
  return raw.filter(isPersistedMessage).map((message) => ({
    id: message.id || createAiAgentMessageId(),
    sender: message.sender,
    text: message.text,
    actionPlan: message.actionPlan,
    isError: message.isError,
  }));
}

function readStoredExecutedIds(messages: Message[]): string[] {
  const raw = readSessionJson<unknown>(EXECUTED_STORAGE_KEY, []);
  if (Array.isArray(raw)) {
    return raw.filter((value): value is string => typeof value === "string");
  }

  const legacyRaw = readSessionJson<unknown>(LEGACY_EXECUTED_STORAGE_KEY, []);
  if (!Array.isArray(legacyRaw)) return [];
  return legacyRaw
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value))
    .map((index) => messages[index]?.id)
    .filter((value): value is string => typeof value === "string");
}

function wait(ms = 180) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

async function waitForElement(selector: string, timeoutMs = 1200): Promise<StepExecutionResult> {
  const startedAt = Date.now();
  while (Date.now() - startedAt <= timeoutMs) {
    if (isVisibleElement(getElement(selector))) {
      return { ok: true };
    }
    await wait(80);
  }
  return { ok: false, message: `${selector} の表示を確認できませんでした。` };
}

function readPendingActionState(): PendingActionState {
  if (typeof window === "undefined") return { steps: [] };
  try {
    const raw = window.sessionStorage.getItem(PENDING_ACTION_STEPS_KEY);
    if (!raw) return { steps: [] };
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return { steps: parsed.filter(isActionStep) };
    }
    if (!parsed || typeof parsed !== "object") return { steps: [] };
    const candidate = parsed as { version?: unknown; steps?: unknown; expectedPath?: unknown; createdAt?: unknown };
    const createdAt = typeof candidate.createdAt === "number" ? candidate.createdAt : Date.now();
    if (Date.now() - createdAt > PENDING_ACTION_EXPIRY_MS) {
      clearPendingActionSteps();
      return { steps: [] };
    }
    const steps = Array.isArray(candidate.steps) ? candidate.steps.filter(isActionStep) : [];
    return {
      steps,
      expectedPath: typeof candidate.expectedPath === "string" ? candidate.expectedPath : undefined,
    };
  } catch {
    return { steps: [] };
  }
}

function writePendingActionSteps(steps: ActionStep[], expectedPath?: string) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(PENDING_ACTION_STEPS_KEY, JSON.stringify({
      version: 2,
      steps,
      expectedPath,
      createdAt: Date.now(),
    }));
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

function getInternalPathname(path: string | undefined) {
  if (!isSafeInternalPath(path) || typeof window === "undefined") return "";
  try {
    return new URL(path, window.location.origin).pathname;
  } catch {
    return "";
  }
}

function getAppActionReadySelectors(step: ActionStep) {
  const command = step.command || "";
  if (command === "chat.fillSetupMessage") return ["[data-agent-id='chat.setup-message']"];
  if (command === "chat.sendSetupMessage") return ["[data-agent-id='chat.send-setup-message']"];
  if (command === "chat.openPromptComposer") return ["#openNewPromptModal"];
  if (command === "chat.toggleTaskOrder") return ["#edit-task-order-btn"];
  if (command === "chat.showChatHistory") return ["#access-chat-btn"];
  if (command === "prompt.search") return ["#searchInput", "#searchButton"];
  if (command === "prompt.openComposer") return ["#heroOpenPostModal"];
  if (command === "prompt.openLogin") return ["#login-btn"];
  if (command === "prompt.scrollResults") return ["#prompt-feed-section"];
  if (command === "settings.openSection") {
    const section = getArg(step.args, "section");
    return section ? [`[data-section="${cssEscape(section)}"]`] : [];
  }
  if (command === "memo.fillForm") {
    return [
      "[data-agent-id='memo.ai-response']",
      "[data-agent-id='memo.title']",
      "[data-agent-id='memo.tags']",
    ];
  }
  if (command === "memo.save") return ["[data-agent-id='memo.save']"];
  return [];
}

function getStepReadySelectors(step: ActionStep) {
  if (step.action === "app_action") return getAppActionReadySelectors(step);
  if (step.selector) return [step.selector];
  return [];
}

async function waitForAnyElement(selectors: string[], timeoutMs = RESUME_READY_TIMEOUT_MS): Promise<StepExecutionResult> {
  if (!selectors.length) return { ok: true };
  const startedAt = Date.now();
  while (Date.now() - startedAt <= timeoutMs) {
    for (const selector of selectors) {
      if (isVisibleElement(getElement(selector))) return { ok: true };
    }
    await wait(100);
  }
  return { ok: false, message: `${selectors[0]} の表示を確認できませんでした。` };
}

async function waitForPagePath(expectedPath: string | undefined, timeoutMs = RESUME_READY_TIMEOUT_MS) {
  if (!expectedPath || typeof window === "undefined") return true;
  const expectedPathname = getInternalPathname(expectedPath);
  if (!expectedPathname) return false;
  const startedAt = Date.now();
  while (Date.now() - startedAt <= timeoutMs) {
    if (window.location.pathname === expectedPathname) return true;
    await wait(100);
  }
  return window.location.pathname === expectedPathname;
}

async function waitForPendingResumeReady(state: PendingActionState): Promise<StepExecutionResult> {
  const pathReady = await waitForPagePath(state.expectedPath);
  if (!pathReady) {
    return { ok: false, message: "移動先ページの表示を確認できませんでした。" };
  }
  if (document.readyState === "loading") {
    await new Promise<void>((resolve) => {
      document.addEventListener("DOMContentLoaded", () => resolve(), { once: true });
    });
  }
  return waitForAnyElement(getStepReadySelectors(state.steps[0]), RESUME_READY_TIMEOUT_MS);
}

function getArg(args: Record<string, unknown> | undefined, key: string) {
  const value = args?.[key];
  return typeof value === "string" ? value : "";
}

function getElement<T extends HTMLElement = HTMLElement>(selector: string): T | null {
  try {
    const element = document.querySelector(selector);
    return element instanceof HTMLElement ? element as T : null;
  } catch {
    return null;
  }
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
    if (!isSafeInternalPath(path)) return { ok: false, message: "移動先パスが不正です。" };
    if (path === window.location.pathname) return { ok: true };
    window.location.href = path;
    return { ok: true };
  }

  if (command === "chat.fillSetupMessage") {
    return setInputValue("[data-agent-id='chat.setup-message']", getArg(args, "text"));
  }
  if (command === "chat.sendSetupMessage") {
    return clickElement("[data-agent-id='chat.send-setup-message']");
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
      ai_response: "[data-agent-id='memo.ai-response']",
      title: "[data-agent-id='memo.title']",
      tags: "[data-agent-id='memo.tags']",
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
    return clickElement("[data-agent-id='memo.save']");
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
    return { ok: isVisibleElement(getElement(step.selector)), message: `${step.selector} の表示を確認できませんでした。` };
  }
  if (step.action === "focus" && step.selector) {
    return { ok: document.activeElement === getElement(step.selector), message: `${step.selector} のフォーカスを確認できませんでした。` };
  }
  if ((step.action === "click" || step.action === "scroll") && step.selector) {
    return { ok: Boolean(getElement(step.selector)), message: `${step.selector} が見つかりませんでした。` };
  }
  return { ok: true };
}

async function executeActionStep(step: ActionStep): Promise<StepExecutionResult> {
  if ((step.risk === "medium" || step.risk === "high") && !await showConfirmModal("この操作は送信や保存を行う可能性があります。実行しますか？")) {
    return { ok: false, message: "ユーザー確認で操作を中止しました。" };
  }

  let result: StepExecutionResult;
  if (step.action === "app_action") {
    const ready = await waitForAnyElement(getAppActionReadySelectors(step), RESUME_READY_TIMEOUT_MS);
    if (!ready.ok) return ready;
    result = executeAppAction(step);
  } else if (step.action === "navigate") {
    const path = step.path;
    if (!isSafeInternalPath(path)) return { ok: false, message: "移動先パスが不正です。" };
    if (path === window.location.pathname) return { ok: true };
    window.location.href = path;
    return { ok: true };
  } else if (step.action === "input") {
    if (!step.selector) return { ok: false, message: "入力先が指定されていません。" };
    await waitForElement(step.selector, 5000);
    result = setInputValue(step.selector, step.value ?? "");
  } else if (step.action === "select") {
    if (!step.selector) return { ok: false, message: "選択先が指定されていません。" };
    await waitForElement(step.selector, 5000);
    result = setSelectValue(step.selector, step.value ?? "");
  } else if (step.action === "check") {
    if (!step.selector) return { ok: false, message: "チェック対象が指定されていません。" };
    await waitForElement(step.selector, 5000);
    result = setCheckedValue(step.selector, step.checked ?? true);
  } else if (step.action === "wait") {
    const timeoutMs = Math.max(0, Math.min(step.timeout_ms ?? 1200, 5000));
    result = step.selector ? await waitForElement(step.selector, timeoutMs) : { ok: true };
    if (!step.selector && timeoutMs > 0) await wait(timeoutMs);
  } else if (step.action === "click") {
    if (!step.selector) return { ok: false, message: "クリック先が指定されていません。" };
    await waitForElement(step.selector, 5000);
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
    const navigationPathname = getInternalPathname(navigationPath);
    const willNavigate = Boolean(navigationPathname) && navigationPathname !== window.location.pathname;

    if (willNavigate && remaining.length) {
      writePendingActionSteps(remaining, navigationPath);
    } else if (!remaining.length) {
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
  const [executingMessageId, setExecutingMessageId] = useState<string | null>(null);
  const [executionProgress, setExecutionProgress] = useState<ExecutionProgress | null>(null);
  const [executedSet, setExecutedSet] = useState<Set<string>>(new Set());
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
      throw await buildAiAgentHttpError(response);
    }

    let assistantText = "応答を取得できませんでした。もう一度試してください。";
    let actionPlan: ActionPlan | undefined;
    let isError = false;

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
        isError = true;
        break;
      }
    }

    return { id: createAiAgentMessageId(), sender: "assistant", text: assistantText, actionPlan, isError };
  };

  const handleSend = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    if (!trimmedInput || isGenerating) return;

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const userMessage: Message = { id: createAiAgentMessageId(), sender: "user", text: trimmedInput };
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
          id: createAiAgentMessageId(),
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
          id: createAiAgentMessageId(),
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

  const handleExecuteActions = async (steps: ActionStep[], messageId: string) => {
    setExecutingMessageId(messageId);
    setExecutionProgress({
      messageId,
      currentStepIndex: null,
      completedStepIndexes: [],
    });
    try {
      const result = await executeActionSteps(steps, (stepIndex, status) => {
        setExecutionProgress((current) => {
          if (!current || current.messageId !== messageId) {
            return {
              messageId,
              currentStepIndex: status === "current" ? stepIndex : null,
              completedStepIndexes: status === "complete" ? [stepIndex] : [],
            };
          }
          const completed = new Set(current.completedStepIndexes);
          if (status === "complete") completed.add(stepIndex);
          return {
            messageId,
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
        setExecutedSet((prev) => new Set([...prev, messageId]));
        if (result.pendingNavigation) {
          const merged = Array.from(new Set([...readStoredExecutedIds(messagesRef.current), messageId]));
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
              { id: createAiAgentMessageId(), sender: "user", text: replanPrompt },
            ],
            controller.signal,
          );
          setMessages((prev) => [
            ...prev,
            {
              id: createAiAgentMessageId(),
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
                id: createAiAgentMessageId(),
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
          id: createAiAgentMessageId(),
          sender: "assistant",
          text: error instanceof Error ? error.message : "操作の実行に失敗しました。",
          isError: true,
        },
      ]);
    } finally {
      setExecutingMessageId(null);
      setExecutionProgress(null);
    }
  };

  useEffect(() => {
    const storedMessages = readStoredMessages();
    const storedExecuted = readStoredExecutedIds(storedMessages);
    if (storedMessages.length) setMessages(storedMessages);
    if (storedExecuted.length) setExecutedSet(new Set(storedExecuted));
    setHydrated(true);

    const pendingActionState = readPendingActionState();
    const pendingSteps = pendingActionState.steps;
    if (!pendingSteps.length) return undefined;

    let timer: number | undefined;
    setMessages((prev) => {
      const pendingMessageId = createAiAgentMessageId();
      timer = window.setTimeout(async () => {
        const ready = await waitForPendingResumeReady(pendingActionState);
        if (!ready.ok) {
          clearPendingActionSteps();
          setMessages((current) => [
            ...current,
            {
              id: createAiAgentMessageId(),
              sender: "assistant",
              text: ready.message || "移動後のページ準備を確認できませんでした。",
              isError: true,
            },
          ]);
          return;
        }
        void handleExecuteActions(pendingSteps, pendingMessageId);
      }, 360);
      return [
        ...prev,
        {
          id: pendingMessageId,
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

  useEffect(() => {
    if (!hydrated) return;
    writeSessionJson(
      MESSAGES_STORAGE_KEY,
      messages.map(({ id, sender, text, actionPlan, isError }) => ({ id, sender, text, actionPlan, isError })),
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
          <div key={msg.id} className={`mini-chat-message mini-chat-message--${msg.sender}`}>
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
                          executionProgress?.messageId === msg.id && executionProgress.currentStepIndex === si
                            ? "is-current"
                            : executionProgress?.messageId === msg.id && executionProgress.completedStepIndexes.includes(si)
                              ? "is-complete"
                              : executedSet.has(msg.id)
                                ? "is-complete"
                                : ""
                        }`.trim()}
                        aria-current={
                          executionProgress?.messageId === msg.id && executionProgress.currentStepIndex === si
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
                    onClick={() => handleExecuteActions(msg.actionPlan!.steps, msg.id)}
                    disabled={executingMessageId === msg.id || executedSet.has(msg.id)}
                    aria-label="操作を実行"
                  >
                    {executingMessageId === msg.id ? (
                      <><i className="bi bi-three-dots"></i> 実行中...</>
                    ) : executedSet.has(msg.id) ? (
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
