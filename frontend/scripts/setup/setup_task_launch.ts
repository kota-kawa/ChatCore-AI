import { isTaskOrderEditing, setCurrentChatRoomId } from "../core/app_state";
import { generateResponse } from "../chat/chat_controller";
import { createNewChatRoom, loadChatRooms } from "../chat/chat_rooms";
import { showChatInterface } from "../chat/chat_ui";

let isTaskLaunchInProgress = false;

export function resetTaskLaunchInProgress() {
  isTaskLaunchInProgress = false;
}

export function initSetupTaskCards() {
  const container = document.getElementById("task-selection");
  if (!container) return;
  container.removeEventListener("click", handleTaskCardClick);
  container.addEventListener("click", handleTaskCardClick);
}

function handleTaskCardClick(e: Event) {
  if (isTaskOrderEditing()) return; // 並び替え中は無視
  if (isTaskLaunchInProgress) return; // 多重送信防止

  const target = e.target as Element | null;
  // 詳細ボタン（▼）経由のクリックではチャット送信しない
  if (target?.closest(".task-detail-toggle")) return;

  const card = target?.closest(".prompt-card") as HTMLElement | null;
  if (!card) return;

  isTaskLaunchInProgress = true;

  const setupInfoElement = document.getElementById("setup-info") as HTMLTextAreaElement | null;
  const aiModelSelect = document.getElementById("ai-model") as HTMLSelectElement | null;
  const chatMessages = document.getElementById("chat-messages");

  // 入力フォームの値（空欄可）
  const setupInfo = setupInfoElement ? setupInfoElement.value.trim() : "";
  const aiModel = aiModelSelect ? aiModelSelect.value : "openai/gpt-oss-120b";

  const taskName = card.dataset.task || "";

  // 新チャットルーム ID とタイトル
  const newRoomId = Date.now().toString();
  const roomTitle = setupInfo || "新規チャット";

  setCurrentChatRoomId(newRoomId);

  // ① ルームをサーバーに作成
  createNewChatRoom(newRoomId, roomTitle)
    .then(() => {
      showChatInterface();
      // 新しいチャットではメッセージ表示をリセット
      if (chatMessages) chatMessages.innerHTML = "";
      loadChatRooms();
      localStorage.removeItem(`chatHistory_${newRoomId}`);

      // ② 最初のメッセージ
      const firstMsg = setupInfo
        ? `【タスク】${taskName}\n【状況・作業環境】${setupInfo}`
        : `【タスク】${taskName}`;

      // ③ Bot 応答生成
      generateResponse(firstMsg, aiModel);
    })
    .catch((err) => {
      isTaskLaunchInProgress = false;
      alert("チャットルーム作成に失敗: " + err);
    });
}
