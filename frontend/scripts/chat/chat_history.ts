// chat_history.ts – 履歴のロード／保存
// --------------------------------------------------

type ChatHistoryMessage = {
  id?: number;
  message: string;
  sender: string;
  timestamp?: string;
};

type ChatHistoryPagination = {
  has_more?: boolean;
  next_before_id?: number | null;
  limit?: number;
};

const CHAT_HISTORY_PAGE_SIZE = 50;
const historyPaginationState = new Map<string, { hasMore: boolean; nextBeforeId: number | null }>();

let chatGenerationPollTimer: number | null = null;

function stopChatGenerationPolling() {
  if (chatGenerationPollTimer === null) return;
  window.clearTimeout(chatGenerationPollTimer);
  chatGenerationPollTimer = null;
}

function readStoredHistory(roomId: string) {
  try {
    const stored = localStorage.getItem(`chatHistory_${roomId}`);
    const parsed = stored ? JSON.parse(stored) : [];
    return Array.isArray(parsed) ? parsed : [];
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
  const existing = readStoredHistory(roomId) as { text?: string; sender?: string }[];
  const normalizedExisting = existing.map((item) => ({
    message: typeof item.text === "string" ? item.text : "",
    sender: typeof item.sender === "string" ? item.sender : ""
  }));
  writeStoredHistory(roomId, [...list, ...normalizedExisting]);
}

function normalizeHistoryMessages(raw: unknown): ChatHistoryMessage[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((entry) => {
    const obj = typeof entry === "object" && entry !== null ? (entry as Record<string, unknown>) : {};
    return {
      id: typeof obj.id === "number" ? obj.id : undefined,
      message: typeof obj.message === "string" ? obj.message : "",
      sender: typeof obj.sender === "string" ? obj.sender : "",
      timestamp: typeof obj.timestamp === "string" ? obj.timestamp : undefined
    };
  });
}

function updateHistoryPagination(roomId: string, pagination: ChatHistoryPagination | null | undefined) {
  historyPaginationState.set(roomId, {
    hasMore: pagination?.has_more === true,
    nextBeforeId: typeof pagination?.next_before_id === "number" ? pagination.next_before_id : null
  });
}

function removeHistoryLoadMoreButton() {
  window.chatMessages?.querySelector(".chat-history-load-more-btn")?.remove();
}

function renderHistoryLoadMoreButton(roomId: string) {
  if (!window.chatMessages || window.currentChatRoomId !== roomId) return;
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
  window.chatMessages.insertBefore(button, window.chatMessages.firstChild);
}

async function fetchChatHistoryPage(roomId: string, beforeId?: number | null) {
  const params = new URLSearchParams({
    room_id: roomId,
    limit: String(CHAT_HISTORY_PAGE_SIZE)
  });
  if (typeof beforeId === "number") {
    params.set("before_id", String(beforeId));
  }

  const response = await fetch(`/api/get_chat_history?${params.toString()}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.error) {
    throw new Error(data.error || "履歴取得に失敗しました。");
  }
  return data;
}

async function loadOlderChatHistory(roomId: string) {
  if (!window.chatMessages || window.currentChatRoomId !== roomId) return;

  const state = historyPaginationState.get(roomId);
  if (!state || !state.hasMore || state.nextBeforeId === null) return;

  const button = window.chatMessages.querySelector<HTMLButtonElement>(".chat-history-load-more-btn");
  if (button) {
    button.disabled = true;
    button.textContent = "読み込み中...";
  }

  try {
    const data = await fetchChatHistoryPage(roomId, state.nextBeforeId);
    if (window.currentChatRoomId !== roomId || !window.chatMessages) return;

    const olderMessages = normalizeHistoryMessages(data.messages);
    const previousScrollHeight = window.chatMessages.scrollHeight;
    const previousScrollTop = window.chatMessages.scrollTop;

    removeHistoryLoadMoreButton();
    [...olderMessages].reverse().forEach((message) => {
      window.displayMessage?.(message.message, message.sender, { prepend: true, autoScroll: false });
    });

    const scrollDelta = window.chatMessages.scrollHeight - previousScrollHeight;
    window.chatMessages.scrollTop = previousScrollTop + scrollDelta;

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
    if (window.currentChatRoomId !== roomId) {
      stopChatGenerationPolling();
      return;
    }

    fetch(`/api/chat_generation_status?room_id=${encodeURIComponent(roomId)}`)
      .then((r) => r.json())
      .then((data) => {
        if (window.currentChatRoomId !== roomId) {
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
  if (!window.currentChatRoomId) {
    stopChatGenerationPolling();
    historyPaginationState.clear();
    if (window.chatMessages) window.chatMessages.innerHTML = "";
    return;
  }
  const roomId = window.currentChatRoomId;

  fetchChatHistoryPage(roomId)
    .then(async (data) => {
      if (!window.chatMessages) return;

      const msgs = normalizeHistoryMessages(data.messages);
      updateHistoryPagination(roomId, data.pagination);

      const scrollToBottom = () => {
        if (window.scrollMessageToBottom) {
          window.scrollMessageToBottom();
        } else if (window.chatMessages?.lastElementChild && window.scrollMessageToTop) {
          window.scrollMessageToTop(window.chatMessages.lastElementChild as HTMLElement);
        }
      };

      const renderMsgs = (list: ChatHistoryMessage[]) => {
        list.forEach((message) => {
          window.displayMessage?.(message.message, message.sender, { autoScroll: false });
        });
      };

      const saveToLocalStorage = (list: ChatHistoryMessage[]) => {
        writeStoredHistory(
          roomId,
          list.map((message) => ({ message: message.message, sender: message.sender }))
        );
      };

      if (!shouldPollStatus) {
        window.chatMessages.innerHTML = "";
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
        const statusData = await statusResp.json();
        if (!statusData.error) {
          isGenerating = statusData.is_generating === true;
          hasReplayableJob = statusData.has_replayable_job === true;
        }
      } catch {
        // ステータス取得失敗時は通常描画にフォールバック
      }

      if (window.currentChatRoomId !== roomId) return;

      window.chatMessages.innerHTML = "";
      stopChatGenerationPolling();

      if (isGenerating) {
        saveToLocalStorage(msgs);
        renderHistoryLoadMoreButton(roomId);
        renderMsgs(msgs);
        renderHistoryLoadMoreButton(roomId);
        scrollToBottom();
        window.connectToGenerationStream?.(roomId);
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
        window.connectToGenerationStream?.(roomId);
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
  if (!window.currentChatRoomId || !window.chatMessages) return;
  const key = `chatHistory_${window.currentChatRoomId}`;
  let history: { text: string; sender: string }[] = [];
  try {
    const stored = localStorage.getItem(key);
    history = stored ? JSON.parse(stored) : [];
  } catch {
    history = [];
  }
  window.chatMessages.innerHTML = "";
  removeHistoryLoadMoreButton();
  history.forEach((item) => {
    window.displayMessage?.(item.text, item.sender, { autoScroll: false });
  });

  if (window.scrollMessageToBottom) {
    window.scrollMessageToBottom();
  } else if (window.chatMessages.lastElementChild && window.scrollMessageToTop) {
    window.scrollMessageToTop(window.chatMessages.lastElementChild as HTMLElement);
  }
}

/* メッセージ1件をローカル保存 */
function saveMessageToLocalStorage(text: string, sender: string) {
  if (!window.currentChatRoomId) return;
  const key = `chatHistory_${window.currentChatRoomId}`;
  let history: { text: string; sender: string }[] = [];
  try {
    const stored = localStorage.getItem(key);
    history = stored ? JSON.parse(stored) : [];
  } catch {
    history = [];
  }
  history.push({ text, sender });
  localStorage.setItem(key, JSON.stringify(history));
}

// ---- window へ公開 ------------------------------
window.loadChatHistory = loadChatHistory;
window.loadLocalChatHistory = loadLocalChatHistory;
window.saveMessageToLocalStorage = saveMessageToLocalStorage;

export {};
