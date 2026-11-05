// ブラウザーで共有するアプリ状態の入口を提供する。
// Provides access to shared browser application state.

let loggedInState: boolean | null = null;

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
