import {
  createAiAgentMessageId,
  cssEscape,
  isActionStep,
  isAllowedNavigationPath,
  isDestructiveActionLabel,
  isSafeInternalPath,
  isUnexpectedAuthRedirect,
  isVisibleElement,
  pathnamesMatch,
  type ActionStep,
  type Message,
  type StepExecutionResult,
} from "./ai_agent";
import { readSessionJson, writeSessionJson } from "../utils";
import { showConfirmModal } from "../../scripts/core/alert_modal";

// アクション実行中の進捗状態を追跡する型定義
// Tracks which step is currently running and which steps have already completed
export type ExecutionProgress = {
  messageId: string;
  currentStepIndex: number | null;
  completedStepIndexes: number[];
};

// ページ遷移をまたぐ操作計画の一時保存状態
// Holds action steps and optional target path to resume after a page reload
export type PendingActionState = {
  steps: ActionStep[];
  expectedPath?: string;
};

// ナビゲーション試行の結果を統一的に表すための型
// Unifies the result of router.push and window.location assignments for callers
export type NavigationOutcome = {
  ok: boolean;
  message?: string;
  /** true when the move stayed in-place (Next router) and the agent is still mounted. */
  clientSide: boolean;
  needsReplan?: boolean;
};

// ページ遷移を抽象化したコールバック型 — 呼び出し元はクライアント/ハードの違いを意識しない
// Abstracted navigation callback so callers don't need to decide between client and hard navigation
export type NavigateInternal = (path: string) => Promise<NavigationOutcome>;

// beforeunload イベントで保存する残ステップのコンテキスト
// Context persisted to sessionStorage when an undetected unload tears down the page mid-plan
export type UnloadContext = { remaining: ActionStep[]; expectedPath?: string } | null;

// MiniChat コンポーネントの外部 API (props の型定義)
// Public API surface for the MiniChat component
export type MiniChatProps = {
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
export type ExecuteOptions = {
  navigateInternal: NavigateInternal;
  setUnloadContext: (context: UnloadContext) => void;
  onStepProgress?: (stepIndex: number, status: "current" | "complete") => void;
};

// デフォルトの候補プロンプト — ユーザーが何を聞けるかをすぐに把握できるように
// Default quick prompts that demonstrate the agent's capabilities to new users
export const QUICK_PROMPTS = [
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
export const MAX_SEND_MESSAGES = 20;
export const MAX_DOM_LENGTH = 12_000;
export const MAX_INPUT_LENGTH = 4_000;
export const RESUME_READY_TIMEOUT_MS = 12_000;

// Internal pages served by Next.js that can be reached with an in-place router push
// (auth pages are intentionally excluded so the agent never silently unmounts mid-plan).
export const CLIENT_NAVIGABLE_ROUTES = new Set([
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
export function getMessageStorageKeys(storageScope?: string): MessageStorageKeys {
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
export function readStoredMessages(storageKeys: MessageStorageKeys): Message[] {
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
export function readStoredExecutedIds(messages: Message[], storageKeys: MessageStorageKeys): string[] {
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
export function clearStoredConversation(storageKeys: MessageStorageKeys) {
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
export function isClientNavigableRoute(pathname: string): boolean {
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
export function readPendingActionState(): PendingActionState {
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
export function writePendingActionSteps(steps: ActionStep[], expectedPath?: string) {
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
export function clearPendingActionSteps() {
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
export function getInternalPathname(path: string | undefined) {
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
export async function waitForRouteSettled(expectedPath: string): Promise<StepExecutionResult> {
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
export async function waitForPendingResumeReady(state: PendingActionState): Promise<StepExecutionResult> {
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
export async function executeActionSteps(
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
export const ACTION_LABELS: Record<ActionStep["action"], string> = {
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
export const INITIAL_PROGRESS_MESSAGE = "依頼を送信しています...";
