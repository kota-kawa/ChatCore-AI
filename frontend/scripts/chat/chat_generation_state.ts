import { getCurrentChatRoomId } from "../core/app_state";
import { API_PATHS } from "../core/constants";
import { getSharedDomRefs } from "../core/dom";

let currentAbortController: AbortController | null = null;
const streamLastEventIdByRoom = new Map<string, number>();

function isGenerating() {
  return currentAbortController !== null;
}

function syncGeneratingUi() {
  const generating = isGenerating();
  const btn = getSharedDomRefs().sendBtn;
  if (!btn) return;
  if (generating) {
    btn.classList.add("send-btn--stop");
    btn.setAttribute("aria-label", "停止");
    btn.setAttribute("data-tooltip", "生成を停止");
    const icon = btn.querySelector("i");
    if (icon) icon.className = "bi bi-stop-fill";
  } else {
    btn.classList.remove("send-btn--stop");
    btn.setAttribute("aria-label", "送信");
    btn.setAttribute("data-tooltip", "メッセージを送信");
    const icon = btn.querySelector("i");
    if (icon) icon.className = "bi bi-send";
  }
}

function beginGeneration(controller: AbortController) {
  currentAbortController = controller;
  syncGeneratingUi();
}

function clearGeneration(controller?: AbortController) {
  if (controller && currentAbortController !== controller) return;
  currentAbortController = null;
  syncGeneratingUi();
}

async function stopGeneration() {
  const abortController = currentAbortController;
  if (abortController) {
    abortController.abort();
    clearGeneration(abortController);
  }
  const currentChatRoomId = getCurrentChatRoomId();
  if (currentChatRoomId) {
    try {
      await fetch(API_PATHS.chatStop, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_room_id: currentChatRoomId })
      });
    } catch {
      // ベストエフォート
    }
  }
}

function getStreamLastEventId(roomId: string) {
  return streamLastEventIdByRoom.get(roomId);
}

function setStreamLastEventId(roomId: string, lastEventId: number) {
  streamLastEventIdByRoom.set(roomId, lastEventId);
}

function deleteStreamLastEventId(roomId: string) {
  streamLastEventIdByRoom.delete(roomId);
}

export {
  beginGeneration,
  clearGeneration,
  deleteStreamLastEventId,
  getStreamLastEventId,
  isGenerating,
  setStreamLastEventId,
  stopGeneration
};
