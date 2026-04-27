import { useState, useRef, useEffect, type FormEvent } from "react";

import { fetchJsonOrThrow } from "../../scripts/core/runtime_validation";

type Message = {
  sender: "user" | "assistant";
  text: string;
};

type AiAgentResponse = {
  response?: string;
  model?: string;
  error?: string;
};

const QUICK_PROMPTS = [
  "このプロンプトを投稿向けに整えて",
  "タイトル案を3つ出して",
  "使いやすい入力例を作って"
];

export function MiniChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
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

    try {
      const { payload } = await fetchJsonOrThrow<AiAgentResponse>(
        "/api/ai-agent",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            messages: nextMessages.map((message) => ({
              role: message.sender,
              content: message.text,
            })),
          }),
        },
        {
          defaultMessage: "AIエージェントの応答生成に失敗しました。",
        }
      );

      const assistantMessage: Message = {
        sender: "assistant",
        text: payload.response?.trim() || "応答を取得できませんでした。もう一度試してください。",
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      const assistantMessage: Message = {
        sender: "assistant",
        text: error instanceof Error
          ? error.message
          : "AIエージェントの応答生成に失敗しました。",
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } finally {
      setIsGenerating(false);
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
              <div className="mini-chat-text">{msg.text}</div>
            </div>
          </div>
        ))}
        {isGenerating ? (
          <div className="mini-chat-message mini-chat-message--assistant mini-chat-message--typing" aria-live="polite">
            <span className="mini-chat-avatar" aria-hidden="true">
              <i className="bi bi-stars"></i>
            </span>
            <div className="mini-chat-text-wrapper">
              <span className="mini-chat-typing-dot"></span>
              <span className="mini-chat-typing-dot"></span>
              <span className="mini-chat-typing-dot"></span>
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
