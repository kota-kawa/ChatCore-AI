// chat_history.ts – 履歴のロード／保存
// --------------------------------------------------
import {
  ChatGenerationStatusResponseSchema,
  ChatHistoryMessageSchema,
  ChatHistoryResponseSchema,
  StoredChatHistoryEntrySchema
} from "../../types/chat";
import type {
  ChatHistoryResponse,
  ChatHistoryPagination
} from "../../types/chat";
import { getCurrentChatRoomId } from "../core/app_state";
import { getSharedDomRefs } from "../core/dom";
import { extractApiErrorMessage, parseJsonText, readJsonBody } from "../core/runtime_validation";
import { connectToGenerationStream } from "./chat_controller";
import { displayMessage } from "./chat_messages";
import { scrollMessageToBottom, scrollMessageToTop } from "./message_utils";

const CHAT_HISTORY_PAGE_SIZE = 50;
const historyPaginationState = new Map<string, { hasMore: boolean; nextBeforeId: number | null }>();

let chatGenerationPollTimer: number | null = null;

type NormalizedChatHistoryMessage = {
  id?: number;
  message: string;
  sender: string;
  timestamp?: string;
};

type StoredHistoryMessage = {
  text: string;
  sender: string;
};

function stopChatGenerationPolling() {
  if (chatGenerationPollTimer === null) return;
  window.clearTimeout(chatGenerationPollTimer);
  chatGenerationPollTimer = null;
}

function normalizeStoredHistory(raw: unknown): StoredHistoryMessage[] {
  if (!Array.isArray(raw)) return [];
  const entries: StoredHistoryMessage[] = [];
  raw.forEach((entry) => {
    const parsed = StoredChatHistoryEntrySchema.safeParse(entry);
    if (!parsed.success) return;
    entries.push({
      text: typeof parsed.data.text === "string" ? parsed.data.text : "",
      sender: typeof parsed.data.sender === "string" ? parsed.data.sender : ""
    });
  });
  return entries;
}

function readStoredHistory(roomId: string): StoredHistoryMessage[] {
  try {
    const stored = localStorage.getItem(`chatHistory_${roomId}`);
    const parsedRaw = stored ? parseJsonText(stored) : [];
    return normalizeStoredHistory(parsedRaw);
  } catch {
    return [];
  }
}

function writeStoredHistory(roomId: string, list: { message: string; sender: string }[]) {
  localStorage.setItem(
    `chatHistory_${roomId}`,
    JSON.stringify(list.map((item) => ({ text: item.message, sender: item.sender })))
  );
}

function prependStoredHistory(roomId: string, list: { message: string; sender: string }[]) {
  const existing = readStoredHistory(roomId);
  const normalizedExisting = existing.map((item) => ({
    message: item.text,
    sender: item.sender
  }));
  writeStoredHistory(roomId, [...list, ...normalizedExisting]);
}

function normalizeHistoryMessages(raw: unknown): NormalizedChatHistoryMessage[] {
  if (!Array.isArray(raw)) return [];
  const messages: NormalizedChatHistoryMessage[] = [];
  raw.forEach((entry) => {
    const parsed = ChatHistoryMessageSchema.safeParse(entry);
    if (!parsed.success) return;
    const data = parsed.data;
    messages.push({
      id: typeof data.id === "number" ? data.id : undefined,
      message: typeof data.message === "string" ? data.message : "",
      sender: typeof data.sender === "string" ? data.sender : "",
      timestamp: typeof data.timestamp === "string" ? data.timestamp : undefined
    });
  });
  return messages;
}

function updateHistoryPagination(roomId: string, pagination: ChatHistoryPagination | null | undefined) {
  historyPaginationState.set(roomId, {
    hasMore: pagination?.has_more === true,
    nextBeforeId: typeof pagination?.next_before_id === "number" ? pagination.next_before_id : null
  });
}

function removeHistoryLoadMoreButton() {
  getSharedDomRefs().chatMessages?.querySelector(".chat-history-load-more-btn")?.remove();
}

function renderHistoryLoadMoreButton(roomId: string) {
  const { chatMessages } = getSharedDomRefs();
  if (!chatMessages || getCurrentChatRoomId() !== roomId) return;
  removeHistoryLoadMoreButton();

  const state = historyPaginationState.get(roomId);
  if (!state || !state.hasMore || state.nextBeforeId === null) return;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "chat-history-load-more-btn";
  button.textContent = "過去のメッセージを読み込む";
  button.addEventListener("click", () => {
    void loadOlderChatHistory(roomId);
  });
  chatMessages.insertBefore(button, chatMessages.firstChild);
}

async function fetchChatHistoryPage(roomId: string, beforeId?: number | null): Promise<ChatHistoryResponse> {
  const params = new URLSearchParams({
    room_id: roomId,
    limit: String(CHAT_HISTORY_PAGE_SIZE)
  });
  if (typeof beforeId === "number") {
    params.set("before_id", String(beforeId));
  }

  const response = await fetch(`/api/get_chat_history?${params.toString()}`);
  const rawPayload = await readJsonBody(response).catch(() => ({}));
  const parsed = ChatHistoryResponseSchema.safeParse(rawPayload);
  const data = parsed.success ? parsed.data : {};
  if (!response.ok || data.error) {
    throw new Error(extractApiErrorMessage(rawPayload, "履歴取得に失敗しました。", response.status));
  }
  return data;
}

async function loadOlderChatHistory(roomId: string) {
  const { chatMessages } = getSharedDomRefs();
  if (!chatMessages || getCurrentChatRoomId() !== roomId) return;

  const state = historyPaginationState.get(roomId);
  if (!state || !state.hasMore || state.nextBeforeId === null) return;

  const button = chatMessages.querySelector<HTMLButtonElement>(".chat-history-load-more-btn");
  if (button) {
    button.disabled = true;
    button.textContent = "読み込み中...";
  }

  try {
    const data = await fetchChatHistoryPage(roomId, state.nextBeforeId);
    if (getCurrentChatRoomId() !== roomId || !chatMessages) return;

    const olderMessages = normalizeHistoryMessages(data.messages);
    const previousScrollHeight = chatMessages.scrollHeight;
    const previousScrollTop = chatMessages.scrollTop;

    removeHistoryLoadMoreButton();
    [...olderMessages].reverse().forEach((message) => {
      displayMessage(message.message, message.sender, { prepend: true, autoScroll: false });
    });

    const scrollDelta = chatMessages.scrollHeight - previousScrollHeight;
    chatMessages.scrollTop = previousScrollTop + scrollDelta;

    prependStoredHistory(
      roomId,
      olderMessages.map((message) => ({ message: message.message, sender: message.sender }))
    );
    updateHistoryPagination(roomId, data.pagination);
    renderHistoryLoadMoreButton(roomId);
  } catch (err) {
    console.error("追加履歴取得失敗:", err);
    if (button) {
      button.disabled = false;
      button.textContent = "過去のメッセージを読み込む";
    }
  }
}

function pollChatGenerationStatus(roomId: string, refreshHistoryOnCompletion = false) {
  stopChatGenerationPolling();

  const poll = () => {
    if (getCurrentChatRoomId() !== roomId) {
      stopChatGenerationPolling();
      return;
    }

    fetch(`/api/chat_generation_status?room_id=${encodeURIComponent(roomId)}`)
      .then(async (response) => {
        const rawPayload = await readJsonBody(response).catch(() => ({}));
        const parsed = ChatGenerationStatusResponseSchema.safeParse(rawPayload);
        return parsed.success ? parsed.data : {};
      })
      .then((data) => {
        if (getCurrentChatRoomId() !== roomId) {
          stopChatGenerationPolling();
          return;
        }

        if (data.error) {
          console.error("chat_generation_status:", data.error);
          stopChatGenerationPolling();
          return;
        }

        if (data.is_generating) {
          chatGenerationPollTimer = window.setTimeout(
            () => pollChatGenerationStatus(roomId, refreshHistoryOnCompletion),
            1500
          );
          return;
        }

        stopChatGenerationPolling();
        if (refreshHistoryOnCompletion) {
          loadChatHistory(false);
        }
      })
      .catch((err) => {
        console.error("生成状態取得失敗:", err);
        chatGenerationPollTimer = window.setTimeout(
          () => pollChatGenerationStatus(roomId, refreshHistoryOnCompletion),
          2500
        );
      });
  };

  chatGenerationPollTimer = window.setTimeout(poll, 0);
}

/* サーバーから履歴取得 */
function loadChatHistory(shouldPollStatus = true) {
  const roomId = getCurrentChatRoomId();
  const { chatMessages } = getSharedDomRefs();

  if (!roomId) {
    stopChatGenerationPolling();
    historyPaginationState.clear();
    if (chatMessages) chatMessages.innerHTML = "";
    return;
  }

  fetchChatHistoryPage(roomId)
    .then(async (data) => {
      if (!chatMessages) return;

      const msgs = normalizeHistoryMessages(data.messages);
      updateHistoryPagination(roomId, data.pagination);

      const scrollToBottom = () => {
        if (chatMessages.lastElementChild instanceof HTMLElement) {
          scrollMessageToTop(chatMessages.lastElementChild);
        } else {
          scrollMessageToBottom();
        }
      };

      const renderMsgs = (list: NormalizedChatHistoryMessage[]) => {
        list.forEach((message) => {
          displayMessage(message.message, message.sender, { autoScroll: false });
        });
      };

      const saveToLocalStorage = (list: NormalizedChatHistoryMessage[]) => {
        writeStoredHistory(
          roomId,
          list.map((message) => ({ message: message.message, sender: message.sender }))
        );
      };

      if (!shouldPollStatus) {
        chatMessages.innerHTML = "";
        renderHistoryLoadMoreButton(roomId);
        saveToLocalStorage(msgs);
        renderMsgs(msgs);
        renderHistoryLoadMoreButton(roomId);
        scrollToBottom();
        stopChatGenerationPolling();
        return;
      }

      let isGenerating = false;
      let hasReplayableJob = false;
      try {
        const statusResp = await fetch(`/api/chat_generation_status?room_id=${encodeURIComponent(roomId)}`);
        const rawPayload = await readJsonBody(statusResp).catch(() => ({}));
        const parsed = ChatGenerationStatusResponseSchema.safeParse(rawPayload);
        const statusData = parsed.success ? parsed.data : {};
        if (!statusData.error) {
          isGenerating = statusData.is_generating === true;
          hasReplayableJob = statusData.has_replayable_job === true;
        }
      } catch {
        // ステータス取得失敗時は通常描画にフォールバック
      }

      if (getCurrentChatRoomId() !== roomId) return;

      chatMessages.innerHTML = "";
      stopChatGenerationPolling();

      if (isGenerating) {
        saveToLocalStorage(msgs);
        renderHistoryLoadMoreButton(roomId);
        renderMsgs(msgs);
        renderHistoryLoadMoreButton(roomId);
        scrollToBottom();
        void connectToGenerationStream(roomId);
      } else if (hasReplayableJob) {
        let lastAssistantIdx = -1;
        for (let i = msgs.length - 1; i >= 0; i -= 1) {
          if (msgs[i].sender === "assistant") {
            lastAssistantIdx = i;
            break;
          }
        }
        const msgsWithoutLast =
          lastAssistantIdx >= 0
            ? [...msgs.slice(0, lastAssistantIdx), ...msgs.slice(lastAssistantIdx + 1)]
            : msgs;
        saveToLocalStorage(msgsWithoutLast);
        renderHistoryLoadMoreButton(roomId);
        renderMsgs(msgsWithoutLast);
        renderHistoryLoadMoreButton(roomId);
        scrollToBottom();
        void connectToGenerationStream(roomId);
      } else {
        saveToLocalStorage(msgs);
        renderHistoryLoadMoreButton(roomId);
        renderMsgs(msgs);
        renderHistoryLoadMoreButton(roomId);
        scrollToBottom();
      }
    })
    .catch((err) => console.error("履歴取得失敗:", err));
}

/* ローカルストレージから履歴読み込み */
function loadLocalChatHistory() {
  const roomId = getCurrentChatRoomId();
  const { chatMessages } = getSharedDomRefs();
  if (!roomId || !chatMessages) return;
  const key = `chatHistory_${roomId}`;
  let history: { text: string; sender: string }[] = [];
  try {
    const stored = localStorage.getItem(key);
    const parsedRaw = stored ? parseJsonText(stored) : [];
    history = normalizeStoredHistory(parsedRaw);
  } catch {
    history = [];
  }
  chatMessages.innerHTML = "";
  removeHistoryLoadMoreButton();
  history.forEach((item) => {
    displayMessage(item.text, item.sender, { autoScroll: false });
  });

  if (chatMessages.lastElementChild instanceof HTMLElement) {
    scrollMessageToTop(chatMessages.lastElementChild);
  } else {
    scrollMessageToBottom();
  }
}

/* メッセージ1件をローカル保存 */
function saveMessageToLocalStorage(text: string, sender: string) {
  const roomId = getCurrentChatRoomId();
  if (!roomId) return;
  const key = `chatHistory_${roomId}`;
  let history: { text: string; sender: string }[] = [];
  try {
    const stored = localStorage.getItem(key);
    const parsedRaw = stored ? parseJsonText(stored) : [];
    history = normalizeStoredHistory(parsedRaw);
  } catch {
    history = [];
  }
  history.push({ text, sender });
  localStorage.setItem(key, JSON.stringify(history));
}

export { loadChatHistory, loadLocalChatHistory, saveMessageToLocalStorage };
