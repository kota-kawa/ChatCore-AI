import { stopGeneration, sendMessage } from "../chat/chat_controller";
import { loadChatRooms, switchChatRoom } from "../chat/chat_rooms";
import { showChatInterface } from "../chat/chat_ui";
import {
  getLoggedInState,
  setCurrentChatRoomId,
  setLoggedInState
} from "./app_state";
import { API_PATHS, AUTH_SUCCESS_HINT, CACHE_TTL_MS, ROUTES, STORAGE_KEYS } from "./constants";
import { getSharedDomRefs } from "./dom";
import {
  initSetupTaskCards,
  initToggleTasks,
  invalidateTasksCache,
  loadTaskCards,
  showSetupForm
} from "../setup/setup";
import { initTaskOrderEditing } from "../setup/task_manager";

function readCachedAuthState() {
  try {
    const cached = localStorage.getItem(STORAGE_KEYS.authStateCache);
    if (cached === "1") return true;
    if (cached === "0") return false;
  } catch {
    // localStorage が使えない環境ではキャッシュを無視
  }
  return null;
}

function isCachedAuthStateFresh() {
  try {
    const cachedAtRaw = localStorage.getItem(STORAGE_KEYS.authStateCachedAt);
    if (!cachedAtRaw) return false;
    const cachedAt = Number(cachedAtRaw);
    if (!Number.isFinite(cachedAt)) return false;
    return Date.now() - cachedAt <= CACHE_TTL_MS.authState;
  } catch {
    return false;
  }
}

function writeCachedAuthState(loggedIn: boolean) {
  try {
    localStorage.setItem(STORAGE_KEYS.authStateCache, loggedIn ? "1" : "0");
    localStorage.setItem(STORAGE_KEYS.authStateCachedAt, String(Date.now()));
  } catch {
    // localStorage が使えない環境では保存をスキップ
  }
}

function consumeAuthSuccessHint() {
  const url = new URL(window.location.href);
  if (url.searchParams.get(AUTH_SUCCESS_HINT.queryParam) !== AUTH_SUCCESS_HINT.successValue) {
    return false;
  }

  writeCachedAuthState(true);
  url.searchParams.delete(AUTH_SUCCESS_HINT.queryParam);

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
          window.location.href = ROUTES.login;
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
  fetch(API_PATHS.currentUser, { credentials: "same-origin" })
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
      fetch(API_PATHS.getChatRooms)
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
        window.location.href = ROUTES.settings;
      });
    }
    if (logoutEl) {
      logoutEl.addEventListener("click", () => {
        void fetch(ROUTES.logout, {
          method: "POST",
          credentials: "same-origin"
        })
          .then((response) => {
            if (response.redirected && response.url) {
              window.location.href = response.url;
              return;
            }
            window.location.href = ROUTES.login;
          })
          .catch(() => {
            window.location.href = ROUTES.login;
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
