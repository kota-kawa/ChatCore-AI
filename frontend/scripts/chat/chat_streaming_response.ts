import { StreamEventDataSchema } from "../../types/chat";
import type { StreamEventPayload, StreamingBotMessageHandle } from "../../types/chat";
import { parseJsonText } from "../core/runtime_validation";
import { renderBotMessageImmediate, startStreamingBotMessage } from "./chat_messages";
import { hideTypingIndicator } from "./chat_ui";

function parseStreamEventBlock(block: string): StreamEventPayload | null {
  const lines = block
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.length > 0);

  if (lines.length === 0) return null;

  let event = "message";
  let eventId: number | undefined;
  const dataLines: string[] = [];

  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      return;
    }
    if (line.startsWith("id:")) {
      const rawId = line.slice(3).trim();
      const parsedId = Number.parseInt(rawId, 10);
      if (Number.isFinite(parsedId) && parsedId > 0) {
        eventId = parsedId;
      }
      return;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  });

  if (dataLines.length === 0) return null;

  try {
    const parsedJson = parseJsonText(dataLines.join("\n"));
    const parsedData = StreamEventDataSchema.safeParse(parsedJson);
    if (!parsedData.success) return null;
    return {
      event,
      id: eventId,
      data: parsedData.data
    };
  } catch (error) {
    console.warn("Failed to parse stream event payload.", error, block);
    return null;
  }
}

async function consumeStreamingChatResponse(
  response: Response,
  thinkingWrap: HTMLElement | null,
  options: { onEventId?: (id: number) => void } = {}
) {
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
    hideTypingIndicator();
    thinkingWrap?.remove();
    thinkingWrap = null;
  };

  const ensureStreamHandle = () => {
    if (streamHandle) return streamHandle;
    dismissThinkingState();
    streamHandle = startStreamingBotMessage();
    if (!streamHandle) {
      throw new Error("ストリーム描画を開始できませんでした。");
    }
    return streamHandle;
  };

  const renderStreamError = (message: string) => {
    dismissThinkingState();
    if (streamHandle !== null) {
      streamHandle.showError(message);
      return;
    }
    renderBotMessageImmediate("エラー: " + message);
  };

  const completeStreamHandle = (handle: StreamingBotMessageHandle | null) => {
    if (handle) {
      handle.complete();
    }
  };

  const processBlock = (block: string) => {
    const parsed = parseStreamEventBlock(block);
    if (!parsed) return;
    if (typeof parsed.id === "number" && parsed.id > 0) {
      options.onEventId?.(parsed.id);
    }

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
        completeStreamHandle(streamHandle);
      } else {
        dismissThinkingState();
        if (responseText) {
          renderBotMessageImmediate(responseText);
        }
      }
      return;
    }

    if (parsed.event === "aborted") {
      completed = true;
      if (streamHandle) {
        completeStreamHandle(streamHandle);
      } else {
        dismissThinkingState();
      }
      return;
    }

    if (parsed.event === "error") {
      streamError = typeof parsed.data.message === "string"
        ? parsed.data.message
        : "ストリーム生成中にエラーが発生しました。";
    }
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() || "";

      blocks.forEach(processBlock);

      if (streamError) {
        renderStreamError(streamError);
        break;
      }

      if (done) break;
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      // ユーザーが停止ボタンを押した場合: 受信済み内容を完了として表示
      dismissThinkingState();
      completeStreamHandle(streamHandle);
      return;
    }
    throw err;
  } finally {
    reader.cancel().catch(() => {});
  }

  if (!completed && !streamError) {
    renderStreamError("ストリームが途中で終了しました。");
  }
}

export { consumeStreamingChatResponse };
