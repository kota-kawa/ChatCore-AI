// chat_controller.ts – 送信ボタン／バックエンド通信
// --------------------------------------------------

type StreamEventPayload = {
  event: string;
  data: Record<string, unknown>;
};

type StreamingBotMessageHandle = {
  appendChunk: (chunk: string) => void;
  complete: () => void;
  showError: (message: string) => void;
};

function createThinkingPlaceholder() {
  if (!window.chatMessages) return null;

  const wrapper = document.createElement("div");
  wrapper.className = "message-wrapper bot-message-wrapper thinking-message-wrapper";

  const thinking = document.createElement("div");
  thinking.className = "thinking-message";
  thinking.setAttribute("role", "status");
  thinking.setAttribute("aria-live", "polite");
  thinking.setAttribute("aria-label", "Thinking");

  const header = document.createElement("div");
  header.className = "thinking-message__header";

  const label = document.createElement("span");
  label.className = "thinking-message__label";
  label.textContent = "Thinking";

  const hint = document.createElement("span");
  hint.className = "thinking-message__hint";
  hint.textContent = "回答を準備中";

  header.append(label, hint);

  const rail = document.createElement("div");
  rail.className = "thinking-message__rail";
  rail.setAttribute("aria-hidden", "true");

  const track = document.createElement("div");
  track.className = "thinking-message__track";

  ["Thinking", "Thinking", "Thinking"].forEach((text) => {
    const segment = document.createElement("span");
    segment.textContent = text;
    track.appendChild(segment);
  });

  rail.appendChild(track);
  thinking.append(header, rail);
  wrapper.appendChild(thinking);
  window.chatMessages.appendChild(wrapper);

  if (window.scrollMessageToBottom) {
    window.scrollMessageToBottom();
  } else if (window.scrollMessageToTop) {
    window.scrollMessageToTop(wrapper);
  }

  return wrapper;
}

function parseStreamEventBlock(block: string): StreamEventPayload | null {
  const lines = block
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.length > 0);

  if (lines.length === 0) return null;

  let event = "message";
  const dataLines: string[] = [];

  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      return;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  });

  if (dataLines.length === 0) return null;

  try {
    return {
      event,
      data: JSON.parse(dataLines.join("\n")) as Record<string, unknown>
    };
  } catch (error) {
    console.warn("Failed to parse stream event payload.", error, block);
    return null;
  }
}

async function consumeStreamingChatResponse(response: Response, thinkingWrap: HTMLElement | null) {
  if (!response.body) {
    throw new Error("ストリーム応答を受信できませんでした。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  let streamError: string | null = null;
  let streamHandle: StreamingBotMessageHandle | null = null;

  const dismissThinkingState = () => {
    window.hideTypingIndicator?.();
    thinkingWrap?.remove();
    thinkingWrap = null;
  };

  const ensureStreamHandle = () => {
    if (streamHandle) return streamHandle;
    dismissThinkingState();
    streamHandle = window.startStreamingBotMessage?.() || null;
    if (!streamHandle) {
      throw new Error("ストリーム描画を開始できませんでした。");
    }
    return streamHandle;
  };

  const renderStreamError = (message: string) => {
    dismissThinkingState();
    const activeStreamHandle = streamHandle as StreamingBotMessageHandle | null;
    if (activeStreamHandle !== null) {
      activeStreamHandle.showError(message);
      return;
    }
    window.renderBotMessageImmediate?.("エラー: " + message);
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";

    blocks.forEach((block) => {
      const parsed = parseStreamEventBlock(block);
      if (!parsed) return;

      if (parsed.event === "chunk") {
        const text = typeof parsed.data.text === "string" ? parsed.data.text : "";
        if (!text) return;
        ensureStreamHandle().appendChunk(text);
        return;
      }

      if (parsed.event === "done") {
        completed = true;
        const responseText = typeof parsed.data.response === "string" ? parsed.data.response : "";
        if (streamHandle) {
          streamHandle.complete();
        } else {
          dismissThinkingState();
          if (responseText) {
            window.renderBotMessageImmediate?.(responseText);
          }
        }
        return;
      }

      if (parsed.event === "error") {
        streamError = typeof parsed.data.message === "string"
          ? parsed.data.message
          : "ストリーム生成中にエラーが発生しました。";
      }
    });

    if (streamError) {
      renderStreamError(streamError);
      break;
    }

    if (done) break;
  }

  if (!completed && !streamError) {
    renderStreamError("ストリームが途中で終了しました。");
  }
}

/* 送信ボタン or Enter 押下 */
function sendMessage() {
  if (!window.userInput) return;
  const message = window.userInput.value.trim();
  if (!message) return;
  const aiModel = window.aiModelSelect ? window.aiModelSelect.value : "openai/gpt-oss-20b";
  window.showTypingIndicator?.();
  generateResponse(message, aiModel);
  window.userInput.value = "";
  window.userInput.style.height = "auto";
}

/* サーバー POST → Bot 応答を描画 */
async function generateResponse(message: string, aiModel: string) {
  if (!window.chatMessages) return;
  // marked の遅延読み込みを先行して開始し、初回描画の崩れを減らす
  window.formatLLMOutput?.("");
  // ユーザーメッセージを即描画
  window.renderUserMessage?.(message);

  // Bot 側の Thinking プレースホルダー
  const thinkingWrap = createThinkingPlaceholder();

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        chat_room_id: window.currentChatRoomId,
        model: aiModel
      })
    });
    const contentType = response.headers.get("content-type") || "";

    if (contentType.includes("text/event-stream")) {
      await consumeStreamingChatResponse(response, thinkingWrap);
      return;
    }

    const data = await response.json();
    window.hideTypingIndicator?.();
    thinkingWrap?.remove();
    if (data && data.response) {
      window.renderBotMessageImmediate?.(data.response);
    } else if (data && data.error) {
      window.renderBotMessageImmediate?.("エラー: " + data.error);
    } else {
      window.renderBotMessageImmediate?.("エラー: 予期しないエラーが発生しました。");
    }
  } catch (err) {
    window.hideTypingIndicator?.();
    thinkingWrap?.remove();
    const errorMessage = err instanceof Error ? err.message : String(err);
    window.renderBotMessageImmediate?.("エラー: " + errorMessage);
  }
}

// ---- window へ公開 ------------------------------
window.sendMessage = sendMessage;
window.generateResponse = generateResponse;

export {};
