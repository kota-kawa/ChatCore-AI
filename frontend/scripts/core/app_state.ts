const CURRENT_CHAT_ROOM_STORAGE_KEY = "currentChatRoomId";

let loggedInState: boolean | null = null;
let currentChatRoomIdLoaded = false;
let currentChatRoomIdState: string | null = null;
let isTaskOrderEditingState = false;
let currentEditingCardState: HTMLElement | null = null;

function dispatchAuthStateChange(loggedIn: boolean) {
  document.dispatchEvent(
    new CustomEvent("authstatechange", {
      detail: { loggedIn }
    })
  );
}

export function setLoggedInState(loggedIn: boolean, options: { notify?: boolean } = {}) {
  loggedInState = loggedIn;
  if (options.notify !== false) {
    dispatchAuthStateChange(loggedIn);
  }
}

export function getLoggedInState() {
  return Boolean(loggedInState);
}

export function hasLoggedInState() {
  return loggedInState !== null;
}

function ensureCurrentChatRoomIdLoaded() {
  if (currentChatRoomIdLoaded) return;
  currentChatRoomIdLoaded = true;
  try {
    currentChatRoomIdState = localStorage.getItem(CURRENT_CHAT_ROOM_STORAGE_KEY);
  } catch {
    currentChatRoomIdState = null;
  }
}

export function getCurrentChatRoomId() {
  ensureCurrentChatRoomIdLoaded();
  return currentChatRoomIdState;
}

export function setCurrentChatRoomId(roomId: string | null, options: { persist?: boolean } = {}) {
  const { persist = true } = options;
  currentChatRoomIdLoaded = true;
  currentChatRoomIdState = roomId;

  if (!persist) return;

  try {
    if (roomId) {
      localStorage.setItem(CURRENT_CHAT_ROOM_STORAGE_KEY, roomId);
    } else {
      localStorage.removeItem(CURRENT_CHAT_ROOM_STORAGE_KEY);
    }
  } catch {
    // localStorage が利用不可でも状態はメモリ上で保持する
  }
}

export function hydrateCurrentChatRoomIdFromStorage() {
  ensureCurrentChatRoomIdLoaded();
  return currentChatRoomIdState;
}

export function setTaskOrderEditingState(isEditingOrder: boolean) {
  isTaskOrderEditingState = isEditingOrder;
}

export function isTaskOrderEditing() {
  return isTaskOrderEditingState;
}

export function setCurrentEditingCard(card: HTMLElement | null) {
  currentEditingCardState = card;
}

export function getCurrentEditingCard() {
  return currentEditingCardState;
}
