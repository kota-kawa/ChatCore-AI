export type SharedDomRefs = {
  setupContainer: HTMLElement | null;
  chatContainer: HTMLElement | null;
  chatMessages: HTMLElement | null;
  userInput: HTMLTextAreaElement | HTMLInputElement | null;
  sendBtn: HTMLElement | null;
  backToSetupBtn: HTMLElement | null;
  newChatBtn: HTMLElement | null;
  chatRoomListEl: HTMLElement | null;
  setupInfoElement: HTMLTextAreaElement | null;
  aiModelSelect: HTMLSelectElement | null;
  accessChatBtn: HTMLElement | null;
  taskSelection: HTMLElement | null;
};

let cachedDomRefs: SharedDomRefs | null = null;

export function initSharedDomRefs(): SharedDomRefs {
  cachedDomRefs = {
    setupContainer: document.getElementById("setup-container"),
    chatContainer: document.getElementById("chat-container"),
    chatMessages: document.getElementById("chat-messages"),
    userInput: document.getElementById("user-input") as HTMLTextAreaElement | HTMLInputElement | null,
    sendBtn: document.getElementById("send-btn"),
    backToSetupBtn: document.getElementById("back-to-setup"),
    newChatBtn: document.getElementById("new-chat-btn"),
    chatRoomListEl: document.getElementById("chat-room-list"),
    setupInfoElement: document.getElementById("setup-info") as HTMLTextAreaElement | null,
    aiModelSelect: document.getElementById("ai-model") as HTMLSelectElement | null,
    accessChatBtn: document.getElementById("access-chat-btn"),
    taskSelection: document.querySelector(".task-selection") as HTMLElement | null
  };

  return cachedDomRefs;
}

export function getSharedDomRefs(): SharedDomRefs {
  return cachedDomRefs || initSharedDomRefs();
}
