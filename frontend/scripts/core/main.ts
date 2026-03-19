/**
 * main.ts
 *
 * ■ ページ初期化（DOMContentLoaded）
 *   - ログイン状態を /api/current_user で確認し、設定ボタンを「ログイン／ユーザーアイコン」に切替
 *   - localStorage から前回の currentChatRoomId を復元
 *   - タスクカードと「もっと見る」ボタンの初期化 (initToggleTasks / initSetupTaskCards)
 *   - 最初はセットアップ画面を表示
 *   - 復帰時にチャット履歴をロード（ローカル＋サーバー）
 *
 * ■ UI 操作のイベント登録
 *   - 新規チャット／これまでのチャットを見る／送信／Enter 送信
 *   - テキストエリアの自動高さ調整
 *   - 「戻る」ボタンでセットアップ画面へ
 *   - 画面クリックでチャットルームの３点メニューを閉じる
 *
 * ■ ユーザーメニュー表示 toggleUserMenu()
 *   - 「設定」「ログアウト」メニューを動的生成・表示・非表示
 */

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

function notifyAuthState(loggedIn: boolean) {
  window.loggedIn = loggedIn;
  document.dispatchEvent(
    new CustomEvent("authstatechange", {
      detail: { loggedIn }
    })
  );
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

function initApp() {
  const authButtons = document.getElementById("auth-buttons");
  const newPromptBtn = document.getElementById("openNewPromptModal");
  const accessChatBtn = document.getElementById("access-chat-btn");
  const userIconEl = document.getElementById("userIcon");
  const loginBtn = document.getElementById("login-btn");
  const newChatBtn = document.getElementById("new-chat-btn");
  const sendBtn = document.getElementById("send-btn");
  const userInput = document.getElementById("user-input") as HTMLInputElement | null;
  const backToSetupBtn = document.getElementById("back-to-setup");
  const chatMessages = document.getElementById("chat-messages");

  const callShowSetupForm = () => {
    if (typeof window.showSetupForm === "function") window.showSetupForm();
  };

  const callSendMessage = () => {
    if (typeof window.sendMessage === "function") window.sendMessage();
  };

  const applyAuthUI = (loggedIn: boolean) => {
    if (!authButtons || !userIconEl) return;

    if (loggedIn) {
      // ログイン時：認証ボタンは隠し、ユーザーアイコンを表示
      authButtons.style.display = "none";
      userIconEl.style.display = "";

      if (newPromptBtn) newPromptBtn.style.display = "";
      if (accessChatBtn) accessChatBtn.style.display = "";

      if (window.initTaskOrderEditing) {
        window.initTaskOrderEditing();
      }
    } else {
      // 未ログイン時：認証ボタンだけ表示、ユーザーアイコンは隠す
      authButtons.style.display = "flex";
      userIconEl.style.display = "none";

      if (loginBtn) {
        loginBtn.onclick = () => {
          window.location.href = "/login";
        };
      }

      // タスク編集ボタンが残っていたら削除
      const editBtn = document.getElementById("edit-task-order-btn");
      if (editBtn) editBtn.remove();

      // 新規プロンプト＆過去チャット閲覧ボタンを非表示
      if (newPromptBtn) newPromptBtn.style.display = "none";
      if (accessChatBtn) accessChatBtn.style.display = "none";
    }
  };

  const refreshTasksForAuthStateChange = () => {
    if (window.invalidateTasksCache) window.invalidateTasksCache();
    if (window.loadTaskCards) window.loadTaskCards({ forceRefresh: true });
  };

  consumeAuthSuccessHint();

  // 前回の認証状態を先に反映し、初期表示のポップインを抑える
  const cachedAuthState = readCachedAuthState();
  if (cachedAuthState !== null) {
    notifyAuthState(cachedAuthState);
    applyAuthUI(cachedAuthState);
  }

  // ▼ログイン状態確認とUI制御
  const canFallBackToCachedState = isCachedAuthStateFresh() && cachedAuthState !== null;
  fetch("/api/current_user", { credentials: "same-origin" })
    .then((res) => res.json())
    .then((data) => {
      const previousLoggedIn = Boolean(window.loggedIn);
      const loggedIn = Boolean(data.logged_in);
      writeCachedAuthState(loggedIn);
      notifyAuthState(loggedIn);
      applyAuthUI(loggedIn);

      if (loggedIn !== previousLoggedIn) {
        refreshTasksForAuthStateChange();
      }
    })
    .catch((err) => {
      console.error("Error checking login status:", err);
      if (!canFallBackToCachedState) {
        notifyAuthState(false);
        applyAuthUI(false);
      }
    });

  // ▼ローカルに保存されていれば現在のチャットルームを復元
  if (localStorage.getItem("currentChatRoomId")) {
    window.currentChatRoomId = localStorage.getItem("currentChatRoomId");
  }

  // ▼初期化
  if (typeof window.initToggleTasks === "function") window.initToggleTasks();
  if (typeof window.initSetupTaskCards === "function") window.initSetupTaskCards();

  // 初期表示はセットアップ
  callShowSetupForm();

  // 新規チャット
  if (newChatBtn) {
    newChatBtn.addEventListener("click", () => {
      window.currentChatRoomId = null;
      localStorage.removeItem("currentChatRoomId");
      if (chatMessages) chatMessages.innerHTML = "";
      callShowSetupForm();
    });
  }

  // 「これまでのチャットを見る」
  if (accessChatBtn) {
    accessChatBtn.addEventListener("click", () => {
      fetch("/api/get_chat_rooms")
        .then((res) => res.json())
        .then((data) => {
          const rooms = Array.isArray(data.rooms) ? data.rooms : [];
          if (rooms.length > 0) {
            // 1件目が最も新しいルームなので切り替え
            if (typeof window.switchChatRoom === "function") window.switchChatRoom(String(rooms[0].id));
          } else {
            // ルームがない場合は空のチャット画面を表示
            if (typeof window.showChatInterface === "function") window.showChatInterface();
            if (typeof window.loadChatRooms === "function") window.loadChatRooms();
            if (chatMessages) chatMessages.innerHTML = "";
          }
        })
        .catch((err) => {
          console.error("ルーム一覧取得失敗:", err);
          if (typeof window.showChatInterface === "function") window.showChatInterface();
          if (typeof window.loadChatRooms === "function") window.loadChatRooms();
          if (chatMessages) chatMessages.innerHTML = "";
        });
    });
  }

  // 送信
  if (sendBtn) sendBtn.addEventListener("click", callSendMessage);

  // Enter 送信 (Shift+Enter で改行)
  if (userInput) {
    userInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        callSendMessage();
      }
    });

    // テキストエリア高さ自動調整
    userInput.addEventListener("input", () => {
      userInput.style.height = "auto";
      userInput.style.height = `${userInput.scrollHeight}px`;
    });
  }

  // 戻るボタン
  if (backToSetupBtn) backToSetupBtn.addEventListener("click", callShowSetupForm);

  // 画面クリックでサイドメニューの 3 点メニューを閉じる
  document.addEventListener("click", () => {
    document.querySelectorAll<HTMLElement>(".room-actions-menu").forEach((menu) => {
      menu.style.display = "none";
    });
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp);
} else {
  initApp();
}

/* ▼ユーザーメニュー（設定 / ログアウト） ---------------------------------------*/
function toggleUserMenu() {
  let menu = document.getElementById("user-menu") as HTMLDivElement | null;

  if (!menu) {
    // メニュー要素を生成
    menu = document.createElement("div");
    menu.id = "user-menu";

    // スタイル設定（モバイル時は static、PC時は右上絶対配置）
    Object.assign(menu.style, {
      position: "absolute",
      top: "60px", // 設定アイコン下に 10px マージン
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

    // メニュー内容
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

    // イベント登録
    const settingsEl = document.getElementById("menu-settings");
    const logoutEl = document.getElementById("menu-logout");
    if (settingsEl) {
      settingsEl.addEventListener("click", () => {
        window.location.href = "/settings";
      });
    }
    if (logoutEl) {
      logoutEl.addEventListener("click", () => {
        window.location.href = "/logout";
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

    // メニュー外クリックで非表示
    document.addEventListener("click", function docClick(e) {
      const btn = document.getElementById("settings-btn");
      const target = e.target as Node | null;
      if (!target) return;
      if (menu && !menu.contains(target) && (!btn || !btn.contains(target))) {
        menu.style.display = "none";
      }
    });
  }

  // 表示/非表示トグル
  menu.style.display = menu.style.display === "block" ? "none" : "block";
}

window.toggleUserMenu = toggleUserMenu;

export {};
