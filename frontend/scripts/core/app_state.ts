import { STORAGE_KEYS } from "./constants";

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
    currentChatRoomIdState = localStorage.getItem(STORAGE_KEYS.currentChatRoomId);
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
      localStorage.setItem(STORAGE_KEYS.currentChatRoomId, roomId);
    } else {
      localStorage.removeItem(STORAGE_KEYS.currentChatRoomId);
    }
  } catch {
    // localStorage が利用不可でも状態はメモリ上で保持する
  }
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
