import { stopGeneration, sendMessage } from "../chat/chat_controller";
import { loadChatRooms, switchChatRoom } from "../chat/chat_rooms";
import { showChatInterface } from "../chat/chat_ui";
import {
  getLoggedInState,
  hydrateCurrentChatRoomIdFromStorage,
  setCurrentChatRoomId,
  setLoggedInState
} from "./app_state";
import { getSharedDomRefs } from "./dom";
import {
  initSetupTaskCards,
  initToggleTasks,
  invalidateTasksCache,
  loadTaskCards,
  showSetupForm
} from "../setup/setup";
import { initTaskOrderEditing } from "../setup/task_manager";

const AUTH_STATE_CACHE_KEY = "chatcore.auth.loggedIn";
const AUTH_STATE_CACHE_AT_KEY = "chatcore.auth.cachedAt";
const AUTH_STATE_CACHE_TTL_MS = 30_000;
const AUTH_SUCCESS_QUERY_PARAM = "auth";
const AUTH_SUCCESS_QUERY_VALUE = "success";

function readCachedAuthState() {
  try {
    const cached = localStorage.getItem(AUTH_STATE_CACHE_KEY);
    if (cached === "1") return true;
    if (cached === "0") return false;
  } catch {
    // localStorage が使えない環境ではキャッシュを無視
  }
  return null;
}

function isCachedAuthStateFresh() {
  try {
    const cachedAtRaw = localStorage.getItem(AUTH_STATE_CACHE_AT_KEY);
    if (!cachedAtRaw) return false;
    const cachedAt = Number(cachedAtRaw);
    if (!Number.isFinite(cachedAt)) return false;
    return Date.now() - cachedAt <= AUTH_STATE_CACHE_TTL_MS;
  } catch {
    return false;
  }
}

function writeCachedAuthState(loggedIn: boolean) {
  try {
    localStorage.setItem(AUTH_STATE_CACHE_KEY, loggedIn ? "1" : "0");
    localStorage.setItem(AUTH_STATE_CACHE_AT_KEY, String(Date.now()));
  } catch {
    // localStorage が使えない環境では保存をスキップ
  }
}

function consumeAuthSuccessHint() {
  const url = new URL(window.location.href);
  if (url.searchParams.get(AUTH_SUCCESS_QUERY_PARAM) !== AUTH_SUCCESS_QUERY_VALUE) {
    return false;
  }

  writeCachedAuthState(true);
  url.searchParams.delete(AUTH_SUCCESS_QUERY_PARAM);

  const nextUrl = `${url.pathname}${url.search}${url.hash}`;
  window.history.replaceState({}, document.title, nextUrl || "/");
  return true;
}

function initMainApp() {
  const authButtons = document.getElementById("auth-buttons");
  const newPromptBtn = document.getElementById("openNewPromptModal");
  const userIconEl = document.getElementById("userIcon");
  const loginBtn = document.getElementById("login-btn");
  const {
    accessChatBtn,
    newChatBtn,
    sendBtn,
    userInput,
    backToSetupBtn,
    chatMessages
  } = getSharedDomRefs();

  const applyAuthUI = (loggedIn: boolean) => {
    if (!authButtons || !userIconEl) return;

    if (loggedIn) {
      authButtons.style.display = "none";
      userIconEl.style.display = "";

      if (newPromptBtn) newPromptBtn.style.display = "";
      if (accessChatBtn) accessChatBtn.style.display = "";

      initTaskOrderEditing();
    } else {
      authButtons.style.display = "flex";
      userIconEl.style.display = "none";

      if (loginBtn) {
        loginBtn.onclick = () => {
          window.location.href = "/login";
        };
      }

      const editBtn = document.getElementById("edit-task-order-btn");
      if (editBtn) editBtn.remove();

      if (newPromptBtn) newPromptBtn.style.display = "none";
      if (accessChatBtn) accessChatBtn.style.display = "none";
    }
  };

  const refreshTasksForAuthStateChange = () => {
    invalidateTasksCache();
    loadTaskCards({ forceRefresh: true });
  };

  consumeAuthSuccessHint();

  const cachedAuthState = readCachedAuthState();
  if (cachedAuthState !== null) {
    setLoggedInState(cachedAuthState);
    applyAuthUI(cachedAuthState);
  }

  const canFallBackToCachedState = isCachedAuthStateFresh() && cachedAuthState !== null;
  fetch("/api/current_user", { credentials: "same-origin" })
    .then((res) => res.json())
    .then((data) => {
      const previousLoggedIn = getLoggedInState();
      const loggedIn = Boolean(data.logged_in);
      writeCachedAuthState(loggedIn);
      setLoggedInState(loggedIn);
      applyAuthUI(loggedIn);

      if (loggedIn !== previousLoggedIn) {
        refreshTasksForAuthStateChange();
      }
    })
    .catch((err) => {
      console.error("Error checking login status:", err);
      if (!canFallBackToCachedState) {
        setLoggedInState(false);
        applyAuthUI(false);
      }
    });

  hydrateCurrentChatRoomIdFromStorage();

  initToggleTasks();
  initSetupTaskCards();

  showSetupForm();

  if (newChatBtn) {
    newChatBtn.addEventListener("click", () => {
      setCurrentChatRoomId(null);
      if (chatMessages) chatMessages.innerHTML = "";
      showSetupForm();
    });
  }

  if (accessChatBtn) {
    accessChatBtn.addEventListener("click", () => {
      fetch("/api/get_chat_rooms")
        .then((res) => res.json())
        .then((data) => {
          const rooms = Array.isArray(data.rooms) ? data.rooms : [];
          if (rooms.length > 0) {
            switchChatRoom(String(rooms[0].id));
          } else {
            showChatInterface();
            loadChatRooms();
            if (chatMessages) chatMessages.innerHTML = "";
          }
        })
        .catch((err) => {
          console.error("ルーム一覧取得失敗:", err);
          showChatInterface();
          loadChatRooms();
          if (chatMessages) chatMessages.innerHTML = "";
        });
    });
  }

  if (sendBtn) {
    sendBtn.addEventListener("click", () => {
      if (sendBtn.classList.contains("send-btn--stop")) {
        void stopGeneration();
      } else {
        sendMessage();
      }
    });
  }

  if (userInput) {
    userInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    userInput.addEventListener("input", () => {
      userInput.style.height = "auto";
      userInput.style.height = `${userInput.scrollHeight}px`;
    });
  }

  if (backToSetupBtn) backToSetupBtn.addEventListener("click", showSetupForm);

  document.addEventListener("click", () => {
    document.querySelectorAll<HTMLElement>(".room-actions-menu").forEach((menu) => {
      menu.style.display = "none";
    });
  });
}

function toggleUserMenu() {
  let menu = document.getElementById("user-menu") as HTMLDivElement | null;

  if (!menu) {
    menu = document.createElement("div");
    menu.id = "user-menu";

    Object.assign(menu.style, {
      position: "absolute",
      top: "60px",
      right: "10px",
      background: "#fff",
      border: "1px solid #ddd",
      borderRadius: "6px",
      boxShadow: "0 2px 4px rgba(0,0,0,.1)",
      zIndex: "1001",
      minWidth: "150px",
      overflow: "hidden"
    });

    document.body.appendChild(menu);

    menu.innerHTML = `
      <div id="menu-settings" style="
           padding:8px 16px; cursor:pointer; display:flex; align-items:center;
           color:#007bff; font-weight:bold; font-size:14px; border-bottom:1px solid #ddd;
           background:#f9f9f9;">
        <i class="bi bi-gear" style="margin-right:6px;font-size:16px;"></i> 設定
      </div>
      <div id="menu-logout" style="
           padding:8px 16px; cursor:pointer; display:flex; align-items:center;
           color:#dc3545; font-weight:bold; font-size:14px; background:#f9f9f9;">
        <i class="bi bi-box-arrow-right" style="margin-right:6px;font-size:16px;"></i> ログアウト
      </div>`;

    const settingsEl = document.getElementById("menu-settings");
    const logoutEl = document.getElementById("menu-logout");
    if (settingsEl) {
      settingsEl.addEventListener("click", () => {
        window.location.href = "/settings";
      });
    }
    if (logoutEl) {
      logoutEl.addEventListener("click", () => {
        void fetch("/logout", {
          method: "POST",
          credentials: "same-origin"
        })
          .then((response) => {
            if (response.redirected && response.url) {
              window.location.href = response.url;
              return;
            }
            window.location.href = "/login";
          })
          .catch(() => {
            window.location.href = "/login";
          });
      });
    }

    const [settingsItem, logoutItem] = [settingsEl, logoutEl];
    if (settingsItem) {
      settingsItem.addEventListener("mouseover", () => {
        settingsItem.style.background = "#e6f0ff";
      });
      settingsItem.addEventListener("mouseout", () => {
        settingsItem.style.background = "#f9f9f9";
      });
    }
    if (logoutItem) {
      logoutItem.addEventListener("mouseover", () => {
        logoutItem.style.background = "#ffe6e6";
      });
      logoutItem.addEventListener("mouseout", () => {
        logoutItem.style.background = "#f9f9f9";
      });
    }

    document.addEventListener("click", function docClick(e) {
      const btn = document.getElementById("settings-btn");
      const target = e.target as Node | null;
      if (!target) return;
      if (menu && !menu.contains(target) && (!btn || !btn.contains(target))) {
        menu.style.display = "none";
      }
    });
  }

  menu.style.display = menu.style.display === "block" ? "none" : "block";
}

export { initMainApp, toggleUserMenu };
