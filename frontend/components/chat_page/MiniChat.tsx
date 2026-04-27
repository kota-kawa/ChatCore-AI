import { useState, useRef, useEffect, type FormEvent } from "react";

import MarkdownContent from "../MarkdownContent";

type ActionStep = {
  action: "app_action" | "click" | "input" | "focus" | "scroll" | "navigate";
  command?: string;
  args?: Record<string, unknown>;
  selector?: string;
  path?: string;
  value?: string;
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
  href?: string;
  role?: string;
};

type StepExecutionResult = {
  ok: boolean;
  message?: string;
};

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

const QUICK_PROMPTS = [
  "このサービスはどんなことができる？",
  "この画面の使い方を教えて",
  "まず何から始めればいい？"
];

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
    summaries.push({
      selector,
      tag: element.tagName.toLowerCase(),
      text: truncateForContext(element.textContent),
      ariaLabel: truncateForContext(element.getAttribute("aria-label")),
      placeholder: truncateForContext(input?.placeholder),
      value: truncateForContext(input?.value, 60),
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
    window.location.href = step.path;
    return { ok: true };
  } else if (step.action === "input") {
    if (!step.selector) return { ok: false, message: "入力先が指定されていません。" };
    result = setInputValue(step.selector, step.value ?? "");
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

async function executeActionSteps(steps: ActionStep[]): Promise<StepExecutionResult> {
  for (const step of steps) {
    const result = await executeActionStep(step);
    if (!result.ok) return result;
  }
  return { ok: true };
}

const ACTION_LABELS: Record<ActionStep["action"], string> = {
  app_action: "操作",
  click: "クリック",
  input: "入力",
  focus: "フォーカス",
  scroll: "スクロール",
  navigate: "移動",
};

const INITIAL_PROGRESS_MESSAGE = "依頼を送信しています...";

export function MiniChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [progressSteps, setProgressSteps] = useState<string[]>([]);
  const [executingIdx, setExecutingIdx] = useState<number | null>(null);
  const [executedSet, setExecutedSet] = useState<Set<number>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);
  const trimmedInput = input.trim();
  const currentProgressText = statusText ?? progressSteps[progressSteps.length - 1] ?? null;

  const appendProgressStep = (message: string) => {
    setStatusText(message);
    setProgressSteps((prev) => (
      prev[prev.length - 1] === message ? prev : [...prev, message]
    ));
  };

  const requestAiAgentMessage = async (nextMessages: Message[]): Promise<Message> => {
    const response = await fetch("/api/ai-agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: nextMessages.map((m) => ({ role: m.sender, content: m.text })),
        current_page: typeof window !== "undefined" ? window.location.pathname : null,
        current_dom: collectVisiblePageDom(),
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

    const userMessage: Message = { sender: "user", text: trimmedInput };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setInput("");
    setIsGenerating(true);
    setStatusText(INITIAL_PROGRESS_MESSAGE);
    setProgressSteps([INITIAL_PROGRESS_MESSAGE]);

    try {
      const assistantMessage = await requestAiAgentMessage(nextMessages);
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          sender: "assistant",
          text: error instanceof Error ? error.message : "AIエージェントの応答生成に失敗しました。",
        },
      ]);
    } finally {
      setIsGenerating(false);
      setStatusText(null);
      setProgressSteps([]);
    }
  };

  const handleExecuteActions = async (steps: ActionStep[], msgIdx: number) => {
    setExecutingIdx(msgIdx);
    try {
      const result = await executeActionSteps(steps);
      if (result.ok) {
        setExecutedSet((prev) => new Set([...prev, msgIdx]));
      } else {
        const failureText = result.message || "画面状態を確認できませんでした。";
        const replanPrompt = [
          "前回の操作計画は実行中に失敗しました。",
          `失敗理由: ${failureText}`,
          "現在の画面DOMを再観測し、成功確認しやすい型付きアクションAPIを優先して、実行可能な操作計画だけを作り直してください。",
        ].join("\n");
        setIsGenerating(true);
        setStatusText("画面を再確認しています...");
        setProgressSteps(["画面を再確認しています..."]);
        const replanMessage = await requestAiAgentMessage([
          ...messages,
          { sender: "user", text: replanPrompt },
        ]);
        setMessages((prev) => [
          ...prev,
          {
            sender: "assistant",
            text: `操作を途中で停止しました。${failureText}`,
          },
          replanMessage,
        ]);
      }
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          sender: "assistant",
          text: error instanceof Error ? error.message : "操作の再計画に失敗しました。",
        },
      ]);
    } finally {
      setExecutingIdx(null);
      setIsGenerating(false);
      setStatusText(null);
      setProgressSteps([]);
    }
  };

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
            <strong>プロンプト作成をサポート</strong>
            <p>内容の整理、タイトル案、利用例づくりを短い会話で進められます。</p>
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
            <div className="mini-chat-text-wrapper">
              {msg.sender === "assistant" ? (
                <MarkdownContent text={msg.text} className="mini-chat-text mini-chat-markdown" />
              ) : (
                <div className="mini-chat-text">{msg.text}</div>
              )}
              {msg.actionPlan && (
                <div className="mini-chat-action-plan">
                  <ol className="mini-chat-action-steps">
                    {msg.actionPlan.steps.map((step, si) => (
                      <li key={si} className="mini-chat-action-step">
                        <span className={`mini-chat-action-badge mini-chat-action-badge--${step.action}`}>
                          {ACTION_LABELS[step.action]}
                        </span>
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
            placeholder="プロンプトについて相談する"
            aria-label="AIサポートへのメッセージ"
          />
          <button
            type="submit"
            className="mini-chat-send-btn"
            disabled={!trimmedInput || isGenerating}
            aria-label="送信"
          >
            <i className={`bi ${isGenerating ? "bi-three-dots" : "bi-arrow-up-short"}`}></i>
          </button>
        </div>
        <button
          type="button"
          className="mini-chat-action-btn"
          onClick={() => setMessages([])}
          disabled={!messages.length || isGenerating}
          aria-label="会話をクリア"
        >
          <i className="bi bi-trash3"></i>
        </button>
      </form>
    </div>
  );
}
