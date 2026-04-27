import { useState, useRef, useEffect, type FormEvent } from "react";

import MarkdownContent from "../MarkdownContent";

type ActionStep = {
  action: "click" | "input" | "focus" | "scroll";
  selector: string;
  value?: string;
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
      if (!block.trim()) continue;
      let eventType = "message";
      let dataLine = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) eventType = line.slice(7).trim();
        else if (line.startsWith("data: ")) dataLine = line.slice(6).trim();
      }
      if (!dataLine) continue;
      try {
        const parsed = JSON.parse(dataLine);
        yield { type: eventType, ...parsed } as AiAgentSseEvent;
      } catch {
        // ignore malformed JSON
      }
    }
  }
}

const QUICK_PROMPTS = [
  "このプロンプトを投稿向けに整えて",
  "タイトル案を3つ出して",
  "使いやすい入力例を作って"
];

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

async function executeActionSteps(steps: ActionStep[]): Promise<void> {
  for (const step of steps) {
    const el = document.querySelector(step.selector);
    if (!el) continue;
    if (step.action === "click") {
      (el as HTMLElement).click();
    } else if (step.action === "input") {
      setNativeValue(el as HTMLInputElement | HTMLTextAreaElement, step.value ?? "");
    } else if (step.action === "focus") {
      (el as HTMLElement).focus();
    } else if (step.action === "scroll") {
      (el as HTMLElement).scrollIntoView({ behavior: "smooth", block: "center" });
    }
    await new Promise<void>((r) => setTimeout(r, 150));
  }
}

const ACTION_LABELS: Record<ActionStep["action"], string> = {
  click: "クリック",
  input: "入力",
  focus: "フォーカス",
  scroll: "スクロール",
};

export function MiniChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [executingIdx, setExecutingIdx] = useState<number | null>(null);
  const [executedSet, setExecutedSet] = useState<Set<number>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);
  const trimmedInput = input.trim();

  const handleSend = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    if (!trimmedInput || isGenerating) return;

    const userMessage: Message = { sender: "user", text: trimmedInput };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setInput("");
    setIsGenerating(true);
    setStatusText(null);

    try {
      const response = await fetch("/api/ai-agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: nextMessages.map((m) => ({ role: m.sender, content: m.text })),
          current_page: typeof window !== "undefined" ? window.location.pathname : null,
        }),
      });

      if (!response.ok) {
        throw new Error(`サーバーエラー (${response.status})`);
      }

      let assistantText = "応答を取得できませんでした。もう一度試してください。";
      let actionPlan: ActionPlan | undefined;

      for await (const event of readSseStream(response)) {
        if (event.type === "progress") {
          setStatusText(event.message);
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

      setMessages((prev) => [...prev, { sender: "assistant", text: assistantText, actionPlan }]);
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
    }
  };

  const handleExecuteActions = async (steps: ActionStep[], msgIdx: number) => {
    setExecutingIdx(msgIdx);
    try {
      await executeActionSteps(steps);
      setExecutedSet((prev) => new Set([...prev, msgIdx]));
    } finally {
      setExecutingIdx(null);
    }
  };

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isGenerating]);

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
              {statusText ? (
                <span className="mini-chat-status-text">{statusText}</span>
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
