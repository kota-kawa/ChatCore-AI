// chat_rooms.ts – ルーム一覧・作成／削除／改名
// --------------------------------------------------
import { getCurrentChatRoomId, setCurrentChatRoomId } from "../core/app_state";
import { showConfirmModal } from "../core/alert_modal";
import { getSharedDomRefs } from "../core/dom";
import { loadChatHistory, loadLocalChatHistory } from "./chat_history";
import { closeChatShareModal, refreshChatShareState } from "./chat_share";
import { closeSidebar, showChatInterface } from "./chat_ui";

type ChatRoom = {
  id: string;
  title?: string;
};

// ルーム一覧は毎回サーバーの正を取得して再描画する
// Always re-fetch canonical room list from server before rendering sidebar.
/* サイドバーにルーム一覧を描画 */
function loadChatRooms() {
  fetch("/api/get_chat_rooms")
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        console.error("get_chat_rooms:", data.error);
        return;
      }
      const chatRoomListEl = getSharedDomRefs().chatRoomListEl;
      if (!chatRoomListEl) return;
      const rooms: ChatRoom[] = Array.isArray(data.rooms) ? data.rooms : [];
      chatRoomListEl.innerHTML = "";

      rooms.forEach((room) => {
        const card = createRoomCard(room);
        chatRoomListEl.appendChild(card);
      });
    })
    .catch((err) => console.error("ルーム一覧取得失敗:", err));
}

/* ルームカード生成（内部 util） */
function createRoomCard(room: ChatRoom) {
  const card = document.createElement("div");
  card.className = "chat-room-card";
  if (room.id === getCurrentChatRoomId()) card.classList.add("active");

  const title = document.createElement("span");
  title.textContent = room.title || "新規チャット";

  // 3点アイコン
  const icon = document.createElement("i");
  icon.className = "bi bi-three-dots-vertical room-actions-icon";
  icon.style.cursor = "pointer";
  icon.style.fontSize = "18px";

  // メニュー
  const menu = buildRoomActionsMenu(room);
  icon.addEventListener("click", (e) => {
    e.stopPropagation();
    document.querySelectorAll<HTMLElement>(".room-actions-menu").forEach((m) => {
      if (m !== menu) m.style.display = "none";
    });
    menu.style.display = menu.style.display === "block" ? "none" : "block";
  });

  // クリックでルーム切替
  card.addEventListener("click", (e) => {
    const target = e.target as Element | null;
    if (target?.closest(".room-actions-icon") || target?.closest(".room-actions-menu")) return;
    switchChatRoom(room.id);
  });

  // 右側コンテナ
  const right = document.createElement("div");
  right.style.display = "flex";
  right.style.alignItems = "center";
  right.style.position = "relative";
  right.style.marginLeft = "auto";
  right.append(icon, menu);

  card.append(title, right);
  return card;
}

/* アクションメニュー生成（内部 util） */
function buildRoomActionsMenu(room: ChatRoom) {
  const menu = document.createElement("div");
  menu.className = "room-actions-menu";
  Object.assign(menu.style, {
    position: "absolute",
    top: "50%",
    right: "0",
    transform: "translateY(-50%)",
    background: "#fff",
    border: "1px solid #ddd",
    borderRadius: "6px",
    boxShadow: "0 2px 4px rgba(0,0,0,.1)",
    zIndex: "10",
    minWidth: "140px",
    overflow: "hidden",
    display: "none"
  });

  // 名前変更
  const rename = document.createElement("div");
  rename.className = "menu-item";
  rename.innerHTML =
    '<i class="bi bi-pencil-square" style="margin-right:6px;"></i> 名前変更';
  decorateMenuItem(rename, "#007bff", "#e6f0ff");
  rename.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.style.display = "none";
    const name = prompt("新しいチャットルーム名", room.title);
    if (name && name.trim()) renameChatRoom(room.id, name.trim());
  });

  // 削除
  const del = document.createElement("div");
  del.className = "menu-item";
  del.innerHTML = '<i class="bi bi-trash" style="margin-right:6px;"></i> 削除';
  decorateMenuItem(del, "#dc3545", "#ffe6e6");
  del.addEventListener("click", async (e) => {
    e.stopPropagation();
    menu.style.display = "none";
    const confirmed = await showConfirmModal(`「${room.title}」を削除しますか？`);
    if (confirmed) {
      deleteChatRoom(room.id);
    }
  });

  menu.append(rename, del);
  return menu;
}

/* メニュー項目スタイル util */
function decorateMenuItem(el: HTMLElement, color: string, hover: string) {
  Object.assign(el.style, {
    padding: "8px 16px",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    fontSize: "14px",
    color: color,
    background: "#f9f9f9",
    borderBottom: "1px solid #ddd"
  });
  el.addEventListener("mouseover", () => (el.style.backgroundColor = hover));
  el.addEventListener("mouseout", () => (el.style.backgroundColor = "#f9f9f9"));
}

/* ルーム切替 */
function switchChatRoom(roomId: string) {
  // 選択状態をローカル保持しつつ、履歴はローカル→サーバーの順で復元する
  // Persist selected room locally, then restore history from local cache and server.
  setCurrentChatRoomId(roomId);
  showChatInterface();
  refreshChatShareState();
  closeSidebar();
  loadChatRooms();
  loadLocalChatHistory();
  loadChatHistory();
}

/* ルーム作成 */
function createNewChatRoom(roomId: string, title: string) {
  return fetch("/api/new_chat_room", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: roomId, title })
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.error) return Promise.reject(data.error);
      return data;
    });
}

/* ルーム削除 */
function deleteChatRoom(roomId: string) {
  fetch("/api/delete_chat_room", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ room_id: roomId })
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.error) alert("削除失敗: " + data.error);
      else {
        // 現在開いているルーム削除時はUI状態も同時に初期化する
        // Reset active room UI state when deleting the currently opened room.
        if (roomId === getCurrentChatRoomId()) {
          setCurrentChatRoomId(null);
          const { chatMessages } = getSharedDomRefs();
          if (chatMessages) chatMessages.innerHTML = "";
          refreshChatShareState();
          closeChatShareModal();
        }
        loadChatRooms();
      }
    })
    .catch((err) => alert("削除失敗: " + err));
}

/* ルーム名変更 */
function renameChatRoom(roomId: string, newTitle: string) {
  fetch("/api/rename_chat_room", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ room_id: roomId, new_title: newTitle })
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.error) alert("名前変更失敗: " + data.error);
      else loadChatRooms();
    })
    .catch((err) => alert("名前変更失敗: " + err));
}

export { loadChatRooms, switchChatRoom, createNewChatRoom, deleteChatRoom, renameChatRoom };
