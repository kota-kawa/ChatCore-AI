// chat_controller.ts – 送信ボタン／バックエンド通信
// --------------------------------------------------
import { ChatJsonResponseSchema } from "../../types/chat";
import { getCurrentChatRoomId } from "../core/app_state";
import { API_PATHS } from "../core/constants";
import { getSharedDomRefs } from "../core/dom";
import { extractApiErrorMessage, readJsonBody } from "../core/runtime_validation";
import { loadChatHistory } from "./chat_history";
import {
  beginGeneration,
  clearGeneration,
  deleteStreamLastEventId,
  getStreamLastEventId,
  isGenerating,
  setStreamLastEventId,
  stopGeneration
} from "./chat_generation_state";
import { renderBotMessageImmediate, renderUserMessage } from "./chat_messages";
import { createThinkingPlaceholder } from "./chat_constellation_loader";
import { consumeStreamingChatResponse } from "./chat_streaming_response";
import { formatLLMOutput, hideTypingIndicator, showTypingIndicator } from "./chat_ui";

/* 送信ボタン or Enter 押下 */
function sendMessage() {
  if (isGenerating()) return;
  const { userInput, aiModelSelect } = getSharedDomRefs();
  if (!userInput) return;
  const message = userInput.value.trim();
  if (!message) return;
  const aiModel = aiModelSelect ? aiModelSelect.value : "openai/gpt-oss-120b";
  showTypingIndicator();
  generateResponse(message, aiModel);
  userInput.value = "";
  userInput.style.height = "auto";
}

/* サーバー POST → Bot 応答を描画 */
async function generateResponse(message: string, aiModel: string) {
  if (!getSharedDomRefs().chatMessages) return;

  const abortController = new AbortController();
  beginGeneration(abortController);

  // marked の遅延読み込みを先行して開始し、初回描画の崩れを減らす
  formatLLMOutput("");
  // ユーザーメッセージを即描画
  renderUserMessage(message);

  // Bot 側の Thinking プレースホルダー
  const thinkingWrap = createThinkingPlaceholder();
  const roomId = getCurrentChatRoomId() || "";
  if (roomId) {
    setStreamLastEventId(roomId, 0);
  }

  try {
    const response = await fetch(API_PATHS.chat, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        chat_room_id: getCurrentChatRoomId(),
        model: aiModel
      }),
      signal: abortController.signal
    });
    const contentType = response.headers.get("content-type") || "";

    // SSE応答なら逐次描画、JSON応答なら一括描画へ分岐する
    // Branch by response type: SSE incremental render vs JSON single render.
    if (contentType.includes("text/event-stream")) {
      await consumeStreamingChatResponse(response, thinkingWrap, {
        onEventId: (id) => {
          if (!roomId) return;
          setStreamLastEventId(roomId, id);
        }
      });
      if (roomId) {
        deleteStreamLastEventId(roomId);
      }
      return;
    }

    if (!contentType.includes("application/json")) {
      const rawText = await response.text();
      throw new Error(rawText.trim() || `サーバーエラー: ${response.status}`);
    }

    const rawPayload = await readJsonBody(response);
    const parsed = ChatJsonResponseSchema.safeParse(rawPayload);
    const data = parsed.success ? parsed.data : null;
    hideTypingIndicator();
    thinkingWrap?.remove();
    if (response.ok && data && typeof data.response === "string" && data.response) {
      renderBotMessageImmediate(data.response);
    } else {
      renderBotMessageImmediate(
        "エラー: " + extractApiErrorMessage(rawPayload, "予期しないエラーが発生しました。", response.status)
      );
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      // ユーザーが停止ボタンを押した場合はエラー表示しない
      hideTypingIndicator();
      thinkingWrap?.remove();
      return;
    }
    hideTypingIndicator();
    thinkingWrap?.remove();
    const errorMessage = err instanceof Error ? err.message : String(err);
    renderBotMessageImmediate("エラー: " + errorMessage);
  } finally {
    clearGeneration(abortController);
  }
}

/* ページ復帰時にバックグラウンド生成ジョブへ再接続してストリーミング表示する */
async function connectToGenerationStream(roomId: string): Promise<void> {
  // 画面再表示時の途中生成を復元するため、サーバーの既存ストリームへ接続し直す
  // Reconnect to server-side generation stream to resume in-progress output after return.
  if (isGenerating()) return;
  const abortController = new AbortController();
  beginGeneration(abortController);

  const thinkingWrap = createThinkingPlaceholder();
  const reconnectLastEventId = getStreamLastEventId(roomId);
  const headers: Record<string, string> = {};
  if (typeof reconnectLastEventId === "number" && reconnectLastEventId > 0) {
    headers["Last-Event-ID"] = String(reconnectLastEventId);
  }
  try {
    const response = await fetch(
      `${API_PATHS.chatGenerationStream}?room_id=${encodeURIComponent(roomId)}`,
      { signal: abortController.signal, headers }
    );
    if (!response.ok) {
      thinkingWrap?.remove();
      loadChatHistory(false);
      return;
    }
    await consumeStreamingChatResponse(response, thinkingWrap, {
      onEventId: (id) => {
        setStreamLastEventId(roomId, id);
      }
    });
    deleteStreamLastEventId(roomId);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      thinkingWrap?.remove();
      return;
    }
    thinkingWrap?.remove();
    loadChatHistory(false);
  } finally {
    clearGeneration(abortController);
  }
}

export { sendMessage, generateResponse, stopGeneration, connectToGenerationStream };
