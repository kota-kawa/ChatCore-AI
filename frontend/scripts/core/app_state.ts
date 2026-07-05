import { STORAGE_KEYS } from "./constants";

let loggedInState: boolean | null = null;
let currentChatRoomIdLoaded = false;
let currentChatRoomIdState: string | null = null;
let isTaskOrderEditingState = false;

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

export function isTaskOrderEditing() {
  return isTaskOrderEditingState;
}
