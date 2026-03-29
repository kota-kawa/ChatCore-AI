import type { CurrentUserResponse } from "./types";
import { setLoggedInState } from "../core/app_state";
import { readCachedAuthState, writeCachedAuthState } from "./storage";

type InitAuthOptions = {
  onLoggedIn?: () => void;
  getHasAutoFilledAuthor: () => boolean;
  setHasAutoFilledAuthor: (value: boolean) => void;
};

export function initPromptShareAuth(options: InitAuthOptions) {
  const { onLoggedIn, getHasAutoFilledAuthor, setHasAutoFilledAuthor } = options;
  const userIcon = document.getElementById("userIcon");
  const authButtons = document.getElementById("auth-buttons");
  let isLoggedIn = false;

  const notifyAuthState = (loggedIn: boolean) => {
    setLoggedInState(loggedIn);
  };

  const applyAuthUI = (loggedIn: boolean) => {
    if (loggedIn) {
      if (authButtons) authButtons.style.display = "none";
      if (userIcon) userIcon.style.display = "";
      return;
    }

    if (authButtons) authButtons.style.display = "";
    if (userIcon) userIcon.style.display = "none";
    const loginBtn = document.getElementById("login-btn");
    if (loginBtn) loginBtn.onclick = () => (window.location.href = "/login");
  };

  function applyDefaultAuthorName(user?: { username?: string } | null) {
    const authorInput = document.getElementById("prompt-author") as HTMLInputElement | null;
    if (!authorInput) {
      return;
    }

    const username = String(user?.username || "").trim();
    if (!username) {
      return;
    }

    const currentValue = authorInput.value.trim();
    const shouldAutofill =
      !currentValue || currentValue === "アイデア職人" || getHasAutoFilledAuthor();

    if (!shouldAutofill) {
      return;
    }

    authorInput.value = username;
    setHasAutoFilledAuthor(true);
  }

  // 前回状態を先に反映してポップインを抑える
  const cachedAuthState = readCachedAuthState();
  if (cachedAuthState !== null) {
    isLoggedIn = cachedAuthState;
    notifyAuthState(cachedAuthState);
    applyAuthUI(cachedAuthState);
  }

  window.setTimeout(() => {
    fetch("/api/current_user")
      .then((res) => (res.ok ? res.json() : { logged_in: false }))
      .then((data: CurrentUserResponse) => {
        isLoggedIn = Boolean(data.logged_in);
        writeCachedAuthState(isLoggedIn);
        notifyAuthState(isLoggedIn);
        applyAuthUI(isLoggedIn);
        if (isLoggedIn) {
          applyDefaultAuthorName(data.user);
          onLoggedIn?.();
        }
      })
      .catch((err) => {
        console.error("Error checking login status:", err);
        notifyAuthState(false);
        applyAuthUI(false);
      });
  }, 0);

  return {
    isLoggedIn: () => isLoggedIn
  };
}
