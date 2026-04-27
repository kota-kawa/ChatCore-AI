import { useState, useRef, useEffect } from "react";

type Message = {
  sender: "user" | "bot";
  text: string;
};

export function MiniChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const handleSend = async () => {
    if (!input.trim() || isGenerating) return;

    const userMessage: Message = { sender: "user", text: input };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsGenerating(true);

    // Mock AI response for now
    setTimeout(() => {
      const botMessage: Message = { sender: "bot", text: "エージェントがサポートします。何をお手伝いしましょうか？" };
      setMessages((prev) => [...prev, botMessage]);
      setIsGenerating(false);
    }, 1000);
  };

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="mini-chat-container">
      <div className="mini-chat-messages" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="mini-chat-placeholder">
            <i className="bi bi-robot mini-chat-robot-icon"></i>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`mini-chat-bubble ${msg.sender}`}>
            <div className="mini-chat-text-wrapper">
              <div className="mini-chat-text">{msg.text}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="mini-chat-input-area">
        <div className="mini-chat-input-wrapper">
          <input
            type="text"
            className="mini-chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder="..."
          />
          <button className="mini-chat-send-btn" onClick={handleSend} disabled={isGenerating}>
            <i className={`bi ${isGenerating ? "bi-three-dots" : "bi-arrow-up-short"}`}></i>
          </button>
        </div>
        <button className="mini-chat-action-btn" onClick={() => setMessages([])}>
          <i className="bi bi-trash3"></i>
        </button>
      </div>
    </div>
  );
}
