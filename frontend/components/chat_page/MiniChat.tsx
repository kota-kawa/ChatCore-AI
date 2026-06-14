import { useRouter } from "next/router";
import { useState, useRef, useEffect, useCallback, useMemo, type FormEvent } from "react";

import {
  buildAiAgentHttpError,
  collectVisiblePageDom,
  createAiAgentMessageId,
  cssEscape,
  isActionStep,
  isAllowedNavigationPath,
  isDestructiveActionLabel,
  isSafeInternalPath,
  isUnexpectedAuthRedirect,
  isVisibleElement,
  pathnamesMatch,
  readSseStream,
  type ActionPlan,
  type ActionStep,
  type Message,
  type StepExecutionResult,
} from "../../lib/chat_page/ai_agent";
import { readSessionJson, writeSessionJson } from "../../lib/utils";
import { showConfirmModal } from "../../scripts/core/alert_modal";
import MarkdownContent from "../MarkdownContent";

// アクション実行中の進捗状態を追跡する型定義
// Tracks which step is currently running and which steps have already completed
type ExecutionProgress = {
  messageId: string;
  currentStepIndex: number | null;
  completedStepIndexes: number[];
};

// ページ遷移をまたぐ操作計画の一時保存状態
// Holds action steps and optional target path to resume after a page reload
type PendingActionState = {
  steps: ActionStep[];
  expectedPath?: string;
};

// ナビゲーション試行の結果を統一的に表すための型
// Unifies the result of router.push and window.location assignments for callers
type NavigationOutcome = {
  ok: boolean;
  message?: string;
  /** true when the move stayed in-place (Next router) and the agent is still mounted. */
  clientSide: boolean;
  needsReplan?: boolean;
};

// ページ遷移を抽象化したコールバック型 — 呼び出し元はクライアント/ハードの違いを意識しない
// Abstracted navigation callback so callers don't need to decide between client and hard navigation
type NavigateInternal = (path: string) => Promise<NavigationOutcome>;

// beforeunload イベントで保存する残ステップのコンテキスト
// Context persisted to sessionStorage when an undetected unload tears down the page mid-plan
type UnloadContext = { remaining: ActionStep[]; expectedPath?: string } | null;

// MiniChat コンポーネントの外部 API (props の型定義)
// Public API surface for the MiniChat component
type MiniChatProps = {
  memoId?: number | string | null;
  storageScope?: string;
  quickPrompts?: string[];
  placeholderTitle?: string;
  placeholderDescription?: string;
  inputPlaceholder?: string;
  enableActions?: boolean;
  persistConversation?: boolean;
};

// 実行オプション — ナビゲーション関数とアンロードコンテキスト更新を受け取る
// Options injected into the step executor to decouple navigation strategy from execution logic
type ExecuteOptions = {
  navigateInternal: NavigateInternal;
  setUnloadContext: (context: UnloadContext) => void;
  onStepProgress?: (stepIndex: number, status: "current" | "complete") => void;
};

// デフォルトの候補プロンプト — ユーザーが何を聞けるかをすぐに把握できるように
// Default quick prompts that demonstrate the agent's capabilities to new users
const QUICK_PROMPTS = [
  "このサービスはどんなことができる？",
  "この画面の使い方を教えて",
  "マニュアルからメモの共有方法を探して",
  "プロンプト共有を開いてメール返信を検索して"
];

// sessionStorage のキー定数 — コンポーネント外の関数からも同じキーを参照できるように集約
// Centralized storage key constants shared between the component and helper functions
const PENDING_ACTION_STEPS_KEY = "globalAiAgent.pendingActionSteps";
const AI_AGENT_OPEN_STATE_KEY = "globalAiAgent.isOpen";
const MESSAGES_STORAGE_KEY = "globalAiAgent.messages";
const MESSAGES_TIMESTAMP_KEY = "globalAiAgent.messagesTimestamp";
const EXECUTED_STORAGE_KEY = "globalAiAgent.executedMessageIds";
const LEGACY_EXECUTED_STORAGE_KEY = "globalAiAgent.executedMessageIndexes";

// スコープ付きストレージキーをまとめた型
// Groups related storage keys so they travel together and don't get mixed up
type MessageStorageKeys = {
  messages: string;
  timestamp: string;
  executed: string;
  legacyExecuted: string;
};

// セッション有効期限と入力制限の定数
// Session and input size limits that prevent stale data and oversized API payloads
const SESSION_EXPIRY_MS = 24 * 60 * 60 * 1000;
const PENDING_ACTION_EXPIRY_MS = 10 * 60 * 1000;
const MAX_SEND_MESSAGES = 20;
const MAX_DOM_LENGTH = 12_000;
const MAX_INPUT_LENGTH = 4_000;
const RESUME_READY_TIMEOUT_MS = 12_000;

// Internal pages served by Next.js that can be reached with an in-place router push
// (auth pages are intentionally excluded so the agent never silently unmounts mid-plan).
const CLIENT_NAVIGABLE_ROUTES = new Set([
  "/",
  "/prompt_share",
  "/prompt_share/manage",
  "/memo",
  "/settings",
]);

// ログインリダイレクト検出時とナビゲーション未完了時のユーザー向けメッセージ
// User-facing messages for auth redirect detection and navigation timeout
const AUTH_REDIRECT_MESSAGE = "ログインが必要なため、ログイン画面を開きました。ログイン後にもう一度お試しください。";
const NAVIGATION_NOT_READY_MESSAGE = "移動先ページの表示を確認できませんでした。";

// sessionStorage に保存されたメッセージが有効な Message 型かを検証する
// Type guard to safely deserialize messages from sessionStorage without trusting raw JSON
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

// storageScope が指定されていれば専用キー、なければグローバルキーを返す
// Returns scoped keys when a storageScope is provided so multiple instances don't share state
function getMessageStorageKeys(storageScope?: string): MessageStorageKeys {
  if (!storageScope) {
    return {
      messages: MESSAGES_STORAGE_KEY,
      timestamp: MESSAGES_TIMESTAMP_KEY,
      executed: EXECUTED_STORAGE_KEY,
      legacyExecuted: LEGACY_EXECUTED_STORAGE_KEY,
    };
  }
  return {
    messages: `${storageScope}.messages`,
    timestamp: `${storageScope}.messagesTimestamp`,
    executed: `${storageScope}.executedMessageIds`,
    legacyExecuted: `${storageScope}.executedMessageIndexes`,
  };
}

// セッションストレージから会話履歴を復元する — 有効期限切れなら自動クリア
// Restores conversation history from sessionStorage, clearing it if the session has expired
function readStoredMessages(storageKeys: MessageStorageKeys): Message[] {
  const timestamp = readSessionJson<number>(storageKeys.timestamp, 0);
  if (timestamp > 0 && Date.now() - timestamp > SESSION_EXPIRY_MS) {
    writeSessionJson(storageKeys.messages, []);
    writeSessionJson(storageKeys.executed, []);
    writeSessionJson(storageKeys.timestamp, 0);
    return [];
  }
  const raw = readSessionJson<unknown>(storageKeys.messages, []);
  if (!Array.isArray(raw)) return [];
  return raw.filter(isPersistedMessage).map((message) => ({
    id: message.id || createAiAgentMessageId(),
    sender: message.sender,
    text: message.text,
    actionPlan: message.actionPlan,
    isError: message.isError,
  }));
}

// 実行済みメッセージIDを復元する — 旧形式（インデックス配列）への後方互換も維持
// Reads executed message IDs, migrating from the legacy index-based format if needed
function readStoredExecutedIds(messages: Message[], storageKeys: MessageStorageKeys): string[] {
  const raw = readSessionJson<unknown>(storageKeys.executed, []);
  if (Array.isArray(raw)) {
    return raw.filter((value): value is string => typeof value === "string");
  }

  // インデックス形式の旧データが残っている場合はID形式に変換して返す
  // Migrate legacy index-based executed list to ID-based format on first read
  const legacyRaw = readSessionJson<unknown>(storageKeys.legacyExecuted, []);
  if (!Array.isArray(legacyRaw)) return [];
  return legacyRaw
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value))
    .map((index) => messages[index]?.id)
    .filter((value): value is string => typeof value === "string");
}

// 会話履歴を sessionStorage からすべて削除する
// Wipes all conversation-related keys from sessionStorage to start fresh
function clearStoredConversation(storageKeys: MessageStorageKeys) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(storageKeys.messages);
    window.sessionStorage.removeItem(storageKeys.timestamp);
    window.sessionStorage.removeItem(storageKeys.executed);
    window.sessionStorage.removeItem(storageKeys.legacyExecuted);
  } catch {
    // ignore storage failures
  }
}

// 指定ミリ秒だけ待機する汎用ユーティリティ — UI の更新を React に委ねるために使用
// General-purpose delay utility used to yield to the event loop between DOM operations
function wait(ms = 180) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

// 次のアニメーションフレームまで待機して React のコミットを確認する
// Waits for one animation frame so React can commit pending state before querying the DOM
function nextFrame(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(() => resolve());
    } else {
      setTimeout(resolve, 16);
    }
  });
}

// パスが Next.js のクライアントサイドルーターで遷移できるかを判定する
// Returns true if the pathname is in the set of routes handled by the Next.js router
function isClientNavigableRoute(pathname: string): boolean {
  return CLIENT_NAVIGABLE_ROUTES.has(pathname);
}

// 指定セレクタの要素が可視になるまでポーリングし、タイムアウト後に失敗を返す
// Polls until the element matching the selector becomes visible or the timeout elapses
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

// sessionStorage からページリロードをまたいで保存された未完了ステップを読み込む
// Reads cross-reload pending action steps, discarding them if they have expired
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

// ページ遷移前に残りステップを永続化し、チャットパネルを開いた状態でリロード後に再開できるようにする
// Persists remaining steps before navigation so the panel can resume execution after reload
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

// 完了または失敗した操作計画のセッションストレージエントリを削除する
// Removes the pending action steps entry once a plan finishes or fails
function clearPendingActionSteps() {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(PENDING_ACTION_STEPS_KEY);
  } catch {
    // ignore storage failures
  }
}

// ステップが navigate または openPage コマンドの場合に目標パスを取得する
// Extracts the navigation destination path from a step, handling both action types
function getStepNavigationPath(step: ActionStep) {
  if (step.action === "navigate") return step.path || "";
  if (step.action === "app_action" && step.command === "navigation.openPage") {
    return getArg(step.args, "path");
  }
  return "";
}

// 内部パスを URL オブジェクト経由でパス名に正規化する
// Normalizes an internal path to its pathname so comparisons are origin-independent
function getInternalPathname(path: string | undefined) {
  if (!isSafeInternalPath(path) || typeof window === "undefined") return "";
  try {
    return new URL(path, window.location.origin).pathname;
  } catch {
    return "";
  }
}

// app_action ステップごとに「ページが準備できた」とみなすセレクタを返す
// Maps each app_action command to the DOM selectors that confirm the target UI is ready
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

// ステップ種別に応じて「実行前に可視確認すべきセレクタ」を返す
// Returns the selectors to await before executing a step, based on its action type
function getStepReadySelectors(step: ActionStep) {
  if (step.action === "app_action") return getAppActionReadySelectors(step);
  if (step.selector) return [step.selector];
  return [];
}

// 複数セレクタのいずれかが可視になるまで待つ — ページの準備確認に使用
// Waits until at least one of the given selectors becomes visible on the page
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

// URL のパス名が期待値と一致するまでポーリングし、認証リダイレクトも検出する
// Polls until location.pathname matches the expected destination or an auth redirect is detected
async function waitForPagePath(
  expectedPath: string | undefined,
  timeoutMs = RESUME_READY_TIMEOUT_MS,
): Promise<StepExecutionResult> {
  if (!expectedPath || typeof window === "undefined") return { ok: true };
  const expectedPathname = getInternalPathname(expectedPath);
  if (!expectedPathname) return { ok: false, message: NAVIGATION_NOT_READY_MESSAGE, needsReplan: false };
  const startedAt = Date.now();
  while (Date.now() - startedAt <= timeoutMs) {
    if (isUnexpectedAuthRedirect(expectedPath, window.location.pathname)) {
      return { ok: false, message: AUTH_REDIRECT_MESSAGE, needsReplan: false };
    }
    if (pathnamesMatch(expectedPathname, window.location.pathname)) return { ok: true };
    await wait(100);
  }
  if (isUnexpectedAuthRedirect(expectedPath, window.location.pathname)) {
    return { ok: false, message: AUTH_REDIRECT_MESSAGE, needsReplan: false };
  }
  return pathnamesMatch(expectedPathname, window.location.pathname)
    ? { ok: true }
    : { ok: false, message: NAVIGATION_NOT_READY_MESSAGE, needsReplan: false };
}

// After a client-side router push, confirm the URL settled on the destination (or an
// auth gate) before letting follow-up steps run against the new page.
async function waitForRouteSettled(expectedPath: string): Promise<StepExecutionResult> {
  const outcome = await waitForPagePath(expectedPath);
  if (!outcome.ok) return outcome;
  // React のコミットが完了するまで 2 フレーム待機する
  // Wait two frames to ensure React has committed the new page's effects before proceeding
  await nextFrame();
  await nextFrame();
  return { ok: true };
}

// リロード後の再開前にページとターゲット要素の準備完了を確認する
// Waits for both the correct URL and the first step's target element before resuming after reload
async function waitForPendingResumeReady(state: PendingActionState): Promise<StepExecutionResult> {
  const pathReady = await waitForPagePath(state.expectedPath);
  if (!pathReady.ok) return pathReady;
  if (document.readyState === "loading") {
    await new Promise<void>((resolve) => {
      document.addEventListener("DOMContentLoaded", () => resolve(), { once: true });
    });
  }
  // Let React commit and run effects on the freshly loaded page before probing the DOM.
  await nextFrame();
  const ready = await waitForAnyElement(getStepReadySelectors(state.steps[0]), RESUME_READY_TIMEOUT_MS);
  // The page loaded but the planned target is absent: the plan was built blind against
  // this destination, so re-observe and re-plan rather than failing outright.
  return ready.ok ? ready : { ...ready, needsReplan: true };
}

// step.args から指定キーの文字列値を安全に取得する
// Safely extracts a string argument from step.args, returning "" when missing or non-string
function getArg(args: Record<string, unknown> | undefined, key: string) {
  const value = args?.[key];
  return typeof value === "string" ? value : "";
}

// document.querySelector のラッパー — 無効なセレクタや非 HTMLElement を安全に処理する
// Wrapper around querySelector that handles invalid selectors and non-HTMLElement matches safely
function getElement<T extends HTMLElement = HTMLElement>(selector: string): T | null {
  try {
    const element = document.querySelector(selector);
    return element instanceof HTMLElement ? element as T : null;
  } catch {
    return null;
  }
}

// React が管理する入力値をバイパスして値を設定し、onChange イベントを発火させる
// Bypasses React's synthetic event system to set a native input value and trigger React handlers
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

// セレクタで指定した input/textarea に値を設定し、結果を返す
// Sets a value on the matched input or textarea and returns whether it was applied
function setInputValue(selector: string, value: string): StepExecutionResult {
  const el = getElement<HTMLInputElement | HTMLTextAreaElement>(selector);
  if (!(el instanceof HTMLInputElement) && !(el instanceof HTMLTextAreaElement)) {
    return { ok: false, message: `${selector} の入力欄が見つかりませんでした。` };
  }
  setNativeValue(el, value);
  return { ok: el.value === value, message: el.value === value ? undefined : `${selector} に入力値を反映できませんでした。` };
}

// セレクタで指定した select 要素の値を変更し、input/change イベントを発火する
// Sets a select element's value and dispatches events so React state updates
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

// チェックボックス・ラジオボタンのチェック状態を設定し、イベントを発火する
// Updates a checkbox or radio button's checked state and fires events for React
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

// 要素を取得してクリックし、無効化されている場合は失敗を返す
// Finds the element and clicks it, returning a failure if it's disabled or missing
function clickElement(selector: string): StepExecutionResult {
  const el = getElement(selector);
  if (!el) return { ok: false, message: `${selector} が見つかりませんでした。` };
  if ((el as HTMLButtonElement).disabled) return { ok: false, message: `${selector} は現在無効です。` };
  el.click();
  return { ok: true };
}

// 要素をスムーズスクロールで画面中央に表示する
// Scrolls the matched element into view so the user can see the context of the action
function scrollElement(selector: string): StepExecutionResult {
  const el = getElement(selector);
  if (!el) return { ok: false, message: `${selector} が見つかりませんでした。` };
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  return { ok: true };
}

// app_action コマンドを解釈してページ内操作を実行する
// Dispatches each app_action command to the corresponding page-level DOM operation
function executeAppAction(step: ActionStep): StepExecutionResult {
  const command = step.command || "";
  const args = step.args || {};

  // navigation.openPage is handled by the unified navigation branch in executeActionStep.

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
    // フォームフィールドを data-agent-id でマッピングして一括入力する
    // Maps each memo field to its data-agent-id selector and fills them in sequence
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

// ステップ実行後に期待する状態が実現されているか DOM を検査する
// Inspects the DOM after execution to confirm the action took visible effect
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
  // A click's effect (navigation, removal, async UI) isn't generically observable, and the
  // target legitimately disappears when it triggers a navigation. The element's presence and
  // enabled state were already confirmed before clicking, so treat the click as done.
  return { ok: true };
}

// ページ遷移ステップを処理し、クライアントサイドとハードナビゲーションを統一的に扱う
// Handles navigate and navigation.openPage steps with a single consistent code path
async function executeNavigation(
  step: ActionStep,
  navigateInternal: NavigateInternal,
): Promise<StepExecutionResult> {
  const path = getStepNavigationPath(step);
  if (!isSafeInternalPath(path)) return { ok: false, message: "移動先パスが不正です。", needsReplan: false };
  if (!isAllowedNavigationPath(path)) {
    return { ok: false, message: "この遷移は許可されていません。", needsReplan: false };
  }
  // Already on the destination: nothing to navigate, let following steps run in place.
  if (pathnamesMatch(getInternalPathname(path), window.location.pathname)) return { ok: true };
  const outcome = await navigateInternal(path);
  if (!outcome.ok) return { ok: false, message: outcome.message, needsReplan: outcome.needsReplan };
  return {
    ok: true,
    navigation: outcome.clientSide ? "client" : "hard",
    navigatedTo: getInternalPathname(path),
  };
}

// ステップ種別を判別して対応する操作関数にディスパッチする
// Dispatches a single step to the appropriate DOM operation based on its action type
function performActionStep(step: ActionStep): StepExecutionResult | Promise<StepExecutionResult> {
  if (step.action === "app_action") {
    return executeAppAction(step);
  }
  if (step.action === "input") {
    if (!step.selector) return { ok: false, message: "入力先が指定されていません。" };
    return setInputValue(step.selector, step.value ?? "");
  }
  if (step.action === "select") {
    if (!step.selector) return { ok: false, message: "選択先が指定されていません。" };
    return setSelectValue(step.selector, step.value ?? "");
  }
  if (step.action === "check") {
    if (!step.selector) return { ok: false, message: "チェック対象が指定されていません。" };
    return setCheckedValue(step.selector, step.checked ?? true);
  }
  if (step.action === "wait") {
    const timeoutMs = Math.max(0, Math.min(step.timeout_ms ?? 1200, 5000));
    if (step.selector) return waitForElement(step.selector, timeoutMs);
    return (async () => {
      if (timeoutMs > 0) await wait(timeoutMs);
      return { ok: true } as StepExecutionResult;
    })();
  }
  if (step.action === "click") {
    if (!step.selector) return { ok: false, message: "クリック先が指定されていません。" };
    return clickElement(step.selector);
  }
  if (step.action === "focus") {
    if (!step.selector) return { ok: false, message: "フォーカス先が指定されていません。" };
    const el = getElement(step.selector);
    if (!el) return { ok: false, message: `${step.selector} が見つかりませんでした。` };
    el.focus();
    return { ok: true };
  }
  if (!step.selector) return { ok: false, message: "スクロール先が指定されていません。" };
  return scrollElement(step.selector);
}

// Wait for the step's target to be present before acting. Navigation/wait manage their own timing.
async function waitForStepTarget(step: ActionStep): Promise<StepExecutionResult> {
  if (step.action === "app_action") {
    return waitForAnyElement(getAppActionReadySelectors(step), RESUME_READY_TIMEOUT_MS);
  }
  if (step.selector && step.action !== "wait" && step.action !== "scroll" && step.action !== "focus") {
    await waitForElement(step.selector, 5000);
  }
  return { ok: true };
}

// A click is treated as destructive when it submits a form or its visible label/attributes
// read as an irreversible action, so we confirm it even if the model rated it low risk.
function isDestructiveStep(step: ActionStep): boolean {
  if (step.action !== "click" || !step.selector) return false;
  const el = getElement(step.selector);
  if (!el) return false;
  if (el instanceof HTMLButtonElement && el.type === "submit") return true;
  if (el instanceof HTMLInputElement && (el.type === "submit" || el.type === "image")) return true;
  // ボタンのラベルテキストや属性をまとめて検査して破壊的操作かを判定する
  // Collects all visible label sources and delegates the destructive check to the shared utility
  const haystack = [
    el.getAttribute("aria-label"),
    el.textContent,
    el.getAttribute("title"),
    el.getAttribute("name"),
    el.getAttribute("value"),
  ].filter(Boolean).join(" ");
  return isDestructiveActionLabel(haystack);
}

// 1 ステップを実行する — ナビゲーション・確認ダイアログ・リトライを含む完全なライフサイクル
// Executes a single step through its full lifecycle: navigate, confirm, perform, verify
async function executeActionStep(
  step: ActionStep,
  navigateInternal: NavigateInternal,
): Promise<StepExecutionResult> {
  if (step.action === "navigate" || (step.action === "app_action" && step.command === "navigation.openPage")) {
    return executeNavigation(step, navigateInternal);
  }

  // Wait once for the target to exist; if it never appears, retrying won't help.
  const ready = await waitForStepTarget(step);
  if (!ready.ok) return ready;

  // Confirm before any state-changing action. Risk is honoured, but destructive controls
  // are also caught here so a low-risk label cannot silently submit/delete/log out.
  const needsConfirmation = step.risk === "medium" || step.risk === "high" || isDestructiveStep(step);
  if (needsConfirmation && !await showConfirmModal("この操作は送信・保存・削除など取り消せない可能性があります。実行してよろしいですか？")) {
    return { ok: false, message: "ユーザー確認で操作を中止しました。", needsReplan: false };
  }

  // Clicks and typed actions can briefly land before the target's React handlers are
  // bound (notably right after a navigation), so retry the perform+verify cycle once.
  const maxAttempts = step.action === "wait" ? 1 : 2;
  let lastResult: StepExecutionResult = { ok: false, message: "操作を実行できませんでした。" };
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (attempt > 0) await wait(280);
    const result = await performActionStep(step);
    if (!result.ok) {
      lastResult = result;
      continue;
    }
    const verified = await verifyStep(step);
    if (verified.ok) return { ok: true };
    lastResult = verified;
  }
  return lastResult;
}

// 操作計画のステップ列を順に実行し、ナビゲーションによるページ消失も安全に処理する
// Executes a sequence of steps, persisting the remainder before any navigation that reloads the page
async function executeActionSteps(
  steps: ActionStep[],
  options: ExecuteOptions,
): Promise<StepExecutionResult> {
  const { navigateInternal, setUnloadContext, onStepProgress } = options;
  for (const [stepIndex, step] of steps.entries()) {
    const remaining = steps.slice(stepIndex + 1);
    const navigationPath = getStepNavigationPath(step);
    const navigationPathname = getInternalPathname(navigationPath);
    const willNavigate = Boolean(navigationPathname) && !pathnamesMatch(navigationPathname, window.location.pathname);

    // Persist the continuation before any step runs: an explicit navigation reloads the
    // page, and an undetected click may unload it. The beforeunload net reads this context.
    setUnloadContext(remaining.length ? { remaining, expectedPath: navigationPathname || undefined } : null);
    if (willNavigate && remaining.length) {
      writePendingActionSteps(remaining, navigationPath);
    } else if (!remaining.length) {
      clearPendingActionSteps();
    }

    onStepProgress?.(stepIndex, "current");
    const result = await executeActionStep(step, navigateInternal);
    if (!result.ok) {
      setUnloadContext(null);
      clearPendingActionSteps();
      return { ...result, failedStepIndex: stepIndex };
    }

    // A full document reload is imminent; remaining steps are already persisted for resume.
    if (result.navigation === "hard" && remaining.length) {
      return { ok: true, pendingNavigation: true };
    }
    // In-place navigation kept us mounted: drop the resume snapshot and keep executing here.
    if (result.navigation === "client") {
      clearPendingActionSteps();
    }

    onStepProgress?.(stepIndex, "complete");
  }

  setUnloadContext(null);
  clearPendingActionSteps();
  return { ok: true };
}

// アクション種別を日本語ラベルに変換するマッピング — UI のステップ一覧に使用
// Maps action type identifiers to Japanese display labels shown in the step list
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

// 送信直後に表示する初期ステータステキスト
// Initial status shown while the request is in flight before the first SSE progress event
const INITIAL_PROGRESS_MESSAGE = "依頼を送信しています...";

// MiniChat — AI エージェントとの会話 UI コンポーネント
// MiniChat — embeddable chat panel that lets users interact with the AI agent
export function MiniChat({
  memoId = null,
  storageScope,
  quickPrompts = QUICK_PROMPTS,
  placeholderTitle = "操作支援エージェント",
  placeholderDescription = "画面の使い方、次の操作、入力内容の整理を短い会話で進められます。",
  inputPlaceholder = "この画面でやりたいことを相談する",
  enableActions = true,
  persistConversation = true,
}: MiniChatProps = {}) {
  const router = useRouter();
  // storageScope が変わったときだけキーを再計算する
  // Recompute storage keys only when storageScope changes to avoid unnecessary object churn
  const storageKeys = useMemo(() => getMessageStorageKeys(storageScope), [storageScope]);
  // memoId を数値に正規化する — 無効値は null にフォールバック
  // Normalizes memoId to a positive integer or null so the API always receives a clean value
  const numericMemoId = useMemo(() => {
    if (memoId === null || memoId === undefined || memoId === "") return null;
    const parsed = Number(memoId);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
  }, [memoId]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [progressSteps, setProgressSteps] = useState<string[]>([]);
  const [executingMessageId, setExecutingMessageId] = useState<string | null>(null);
  const [executionProgress, setExecutionProgress] = useState<ExecutionProgress | null>(null);
  const [executedSet, setExecutedSet] = useState<Set<string>>(new Set());
  // ハイドレーション完了フラグ — SSR とクライアント状態の不一致を防ぐ
  // Hydration flag prevents rendering stale server-side state before client storage is read
  const [hydrated, setHydrated] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  // 非同期ハンドラが最新のメッセージを参照できるように ref で同期させる
  // Keeps a ref in sync so async callbacks always see the latest messages without stale closures
  const messagesRef = useRef<Message[]>([]);
  const unloadContextRef = useRef<UnloadContext>(null);
  const routerRef = useRef(router);
  const trimmedInput = input.trim();

  // Keep router ref current so the stable navigateInternal callback always pushes via the
  // latest router instance.
  useEffect(() => {
    routerRef.current = router;
  }, [router]);

  // Safety net: if an undetected click (e.g. a plain link or form submit) tears the page
  // down mid-execution, persist the remaining steps so they resume after the reload.
  useEffect(() => {
    const onBeforeUnload = () => {
      const context = unloadContextRef.current;
      if (context && context.remaining.length) {
        writePendingActionSteps(context.remaining, context.expectedPath);
      }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  // クライアントサイドを優先し、失敗した場合はフルロードにフォールバックする
  // Prefers client-side navigation for smooth UX and falls back to hard navigation when needed
  const navigateInternal = useCallback<NavigateInternal>(async (path) => {
    if (!isSafeInternalPath(path) || !isAllowedNavigationPath(path)) {
      return { ok: false, message: "この遷移は許可されていません。", clientSide: false, needsReplan: false };
    }
    const targetPathname = getInternalPathname(path);
    if (targetPathname && isClientNavigableRoute(targetPathname)) {
      try {
        await routerRef.current.push(path);
        const settled = await waitForRouteSettled(path);
        return { ok: settled.ok, message: settled.message, clientSide: true, needsReplan: settled.needsReplan };
      } catch {
        // Client navigation failed; fall back to a full document load below.
      }
    }
    window.location.href = path;
    return { ok: true, clientSide: false };
  }, []);

  const setUnloadContext = useCallback((context: UnloadContext) => {
    unloadContextRef.current = context;
  }, []);
  const currentProgressText = statusText ?? progressSteps[progressSteps.length - 1] ?? null;

  // Keep ref in sync for stale-closure-safe access in async handlers
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // 重複する進捗メッセージを除去してステップリストに追加する
  // Appends a progress step, skipping it if it's identical to the last entry to avoid duplicates
  const appendProgressStep = (message: string) => {
    setStatusText(message);
    setProgressSteps((prev) => (
      prev[prev.length - 1] === message ? prev : [...prev, message]
    ));
  };

  // AI エージェント API を呼び出し、SSE ストリームから最終応答を構築する
  // Calls the AI agent API and parses the SSE stream to build the assistant message
  const requestAiAgentMessage = async (
    nextMessages: Message[],
    signal: AbortSignal,
  ): Promise<Message> => {
    const response = await fetch("/api/ai-agent", {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        // 直近 MAX_SEND_MESSAGES 件に絞ってペイロードサイズを制限する
        // Limits history to MAX_SEND_MESSAGES to keep the API payload manageable
        messages: nextMessages.slice(-MAX_SEND_MESSAGES).map((m) => ({ role: m.sender, content: m.text })),
        current_page: typeof window !== "undefined" ? window.location.pathname : null,
        current_dom: enableActions ? collectVisiblePageDom().slice(0, MAX_DOM_LENGTH) : "",
        ...(numericMemoId ? { memo_id: numericMemoId } : {}),
      }),
    });

    if (!response.ok) {
      throw await buildAiAgentHttpError(response);
    }

    let assistantText = "応答を取得できませんでした。もう一度試してください。";
    let actionPlan: ActionPlan | undefined;
    let isError = false;

    // SSE イベントを逐次処理してプログレスと最終応答を分離する
    // Processes SSE events incrementally, separating progress updates from the final response
    for await (const event of readSseStream(response)) {
      if (event.type === "progress") {
        appendProgressStep(event.message);
      } else if (event.type === "done") {
        assistantText = event.response.trim() || assistantText;
        break;
      } else if (event.type === "action_plan") {
        assistantText = event.description;
        actionPlan = enableActions ? { description: event.description, steps: event.steps } : undefined;
        break;
      } else if (event.type === "error") {
        assistantText = event.message;
        isError = true;
        break;
      }
    }

    return { id: createAiAgentMessageId(), sender: "assistant", text: assistantText, actionPlan, isError };
  };

  // ユーザーのメッセージを送信し、AI 応答を受け取ってチャットに追加する
  // Sends the user's input to the AI agent and appends the response to the conversation
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
      // AbortError はユーザーが意図的に停止したため静かに無視する
      // AbortError is intentional (user clicked stop), so suppress it silently
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

  // 進行中の AI 応答を中断する
  // Aborts the in-flight API request so generation stops immediately
  const handleStop = () => {
    abortControllerRef.current?.abort();
  };

  // エラーメッセージを除いて直前の会話状態に戻し、再送信する
  // Removes the error message and retries the request from the last valid conversation state
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

  // テキストをクリップボードにコピーし、2 秒後にアイコンを元に戻す
  // Copies text to the clipboard and resets the copied state after 2 seconds
  const handleCopy = async (text: string, index: number) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex((prev) => (prev === index ? null : prev)), 2000);
    } catch {
      // clipboard API unavailable
    }
  };

  // Re-observe the current page and ask the model for a fresh, executable plan. Used both
  // when a step fails mid-flight and when post-navigation targets can't be found.
  const replanAfterFailure = async (failureText: string, failedStepIndex?: number) => {
    const failedStepText = typeof failedStepIndex === "number"
      ? `失敗ステップ: ${failedStepIndex + 1}`
      : "";
    // 最新の DOM 状態を含む再計画プロンプトを構築する
    // Builds a replan prompt that includes the failure reason so the model can adapt its plan
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
  };

  // アクション計画を実行し、進捗状態を更新し、失敗時は再計画を試みる
  // Runs an action plan, tracks per-step progress, and triggers replanning on failure
  const handleExecuteActions = async (steps: ActionStep[], messageId: string) => {
    setExecutingMessageId(messageId);
    setExecutionProgress({
      messageId,
      currentStepIndex: null,
      completedStepIndexes: [],
    });
    try {
      const result = await executeActionSteps(steps, {
        navigateInternal,
        setUnloadContext,
        // ステップの current/complete 遷移ごとに UI の進捗表示を更新する
        // Updates the step-level progress indicator as each step transitions to current or complete
        onStepProgress: (stepIndex, status) => {
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
        },
      });
      if (result.ok) {
        setExecutedSet((prev) => new Set([...prev, messageId]));
        // ページ遷移が発生した場合は実行済み ID をストレージに先行保存する
        // Eagerly persists the executed ID when navigation is pending so it survives the reload
        if (persistConversation && result.pendingNavigation) {
          const merged = Array.from(new Set([...readStoredExecutedIds(messagesRef.current, storageKeys), messageId]));
          writeSessionJson(storageKeys.executed, merged);
        }
      } else if (result.needsReplan === false) {
        // A terminal, self-explanatory stop (e.g. login required): just inform the user.
        setMessages((prev) => [
          ...prev,
          {
            id: createAiAgentMessageId(),
            sender: "assistant",
            text: result.message || "操作を完了できませんでした。",
            isError: true,
          },
        ]);
      } else {
        await replanAfterFailure(result.message || "画面状態を確認できませんでした。", result.failedStepIndex);
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
      setUnloadContext(null);
      setExecutingMessageId(null);
      setExecutionProgress(null);
    }
  };

  // 初回マウント時にセッションストレージから会話・実行済みセット・未完了ステップを復元する
  // On mount, restores conversation history and resumes any cross-reload pending action steps
  useEffect(() => {
    if (!persistConversation) {
      clearStoredConversation(storageKeys);
      setMessages([]);
      setExecutedSet(new Set());
      setHydrated(true);
      return undefined;
    }

    const storedMessages = readStoredMessages(storageKeys);
    const storedExecuted = readStoredExecutedIds(storedMessages, storageKeys);
    if (storedMessages.length) setMessages(storedMessages);
    if (storedExecuted.length) setExecutedSet(new Set(storedExecuted));
    setHydrated(true);

    if (!enableActions) return undefined;

    const pendingActionState = readPendingActionState();
    const pendingSteps = pendingActionState.steps;
    if (!pendingSteps.length) return undefined;

    let timer: number | undefined;
    setMessages((prev) => {
      const pendingMessageId = createAiAgentMessageId();
      // ページ準備完了を確認してから再開実行を開始する
      // Defers execution until waitForPendingResumeReady confirms the page is ready
      timer = window.setTimeout(async () => {
        const ready = await waitForPendingResumeReady(pendingActionState);
        if (!ready.ok) {
          clearPendingActionSteps();
          if (ready.needsReplan) {
            // The destination loaded but the blind-planned targets aren't there: re-observe.
            void replanAfterFailure(ready.message || "移動後のページ準備を確認できませんでした。");
          } else {
            setMessages((current) => [
              ...current,
              {
                id: createAiAgentMessageId(),
                sender: "assistant",
                text: ready.message || "移動後のページ準備を確認できませんでした。",
                isError: true,
              },
            ]);
          }
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
  }, [enableActions, persistConversation, storageKeys]);

  // メッセージが変わるたびにセッションストレージを更新して会話を永続化する
  // Syncs messages to sessionStorage on every change so the conversation survives page reloads
  useEffect(() => {
    if (!hydrated || !persistConversation) return;
    writeSessionJson(
      storageKeys.messages,
      messages.map(({ id, sender, text, actionPlan, isError }) => ({ id, sender, text, actionPlan, isError })),
    );
    writeSessionJson(storageKeys.timestamp, messages.length > 0 ? Date.now() : 0);
  }, [hydrated, messages, persistConversation, storageKeys]);

  // 実行済みセットが変わるたびにストレージを更新する
  // Persists executed message IDs whenever the set changes so they survive reloads
  useEffect(() => {
    if (!hydrated || !persistConversation) return;
    writeSessionJson(storageKeys.executed, Array.from(executedSet));
  }, [hydrated, executedSet, persistConversation, storageKeys]);

  // 新しいメッセージや進捗テキストが追加されたら最下部にスクロールする
  // Scrolls the message list to the bottom whenever content changes so the latest reply is visible
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isGenerating, statusText, progressSteps.length]);

  return (
    <div className="mini-chat-container">
      <div className="mini-chat-messages" ref={scrollRef}>
        {/* メッセージがない場合はプレースホルダーと候補プロンプトを表示する */}
        {/* Show placeholder content and quick prompt suggestions when the conversation is empty */}
        {messages.length === 0 && (
          <div className="mini-chat-placeholder">
            <span className="mini-chat-robot-icon" aria-hidden="true">
              <i className="bi bi-stars"></i>
            </span>
            <strong>{placeholderTitle}</strong>
            <p>{placeholderDescription}</p>
            <div className="mini-chat-suggestions" aria-label="入力候補">
              {quickPrompts.map((prompt) => (
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
        {/* 各メッセージをアバターとコンテンツエリアで描画する */}
        {/* Renders each message with its avatar and content area, using sender-specific styles */}
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
              {/* アクション計画が含まれている場合、ステップ一覧と実行ボタンを表示する */}
              {/* Renders the action plan step list and execute button when an action plan is attached */}
              {enableActions && msg.actionPlan && (
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
              {/* アシスタントのメッセージにはコピーボタンとエラー時の再試行ボタンを表示する */}
              {/* Shows copy and (on error) retry actions beneath each assistant message */}
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
        {/* 生成中はタイピングインジケーターまたは SSE 進捗ステップを表示する */}
        {/* Shows a typing indicator or SSE progress list while the AI response is streaming */}
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
            placeholder={inputPlaceholder}
            aria-label="AIサポートへのメッセージ"
            maxLength={MAX_INPUT_LENGTH}
            disabled={isGenerating}
          />
          {/* 生成中は停止ボタン、それ以外は送信ボタンを表示する */}
          {/* Toggles between stop and send buttons based on whether generation is in progress */}
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
        {/* 会話履歴をクリアするボタン — メッセージがないか生成中は無効化 */}
        {/* Clears the conversation history; disabled while generating or when there's nothing to clear */}
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
          <i className="bi bi-arrow-counterclockwise"></i>
        </button>
      </form>
    </div>
  );
}
