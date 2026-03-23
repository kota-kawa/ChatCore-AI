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
  if (window.isEditingOrder) return; // 並び替え中は無視
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
  const aiModel = aiModelSelect ? aiModelSelect.value : "openai/gpt-oss-20b";

  const taskName = card.dataset.task || "";

  // 新チャットルーム ID とタイトル
  const newRoomId = Date.now().toString();
  const roomTitle = setupInfo || "新規チャット";

  // currentChatRoomId はグローバルまたは他で定義されている前提
  window.currentChatRoomId = newRoomId;
  localStorage.setItem("currentChatRoomId", newRoomId);

  // ① ルームをサーバーに作成
  if (typeof window.createNewChatRoom === "function") {
    window.createNewChatRoom(newRoomId, roomTitle)
      .then(() => {
        if (typeof window.showChatInterface === "function") window.showChatInterface();
        // 新しいチャットではメッセージ表示をリセット
        if (chatMessages) chatMessages.innerHTML = "";
        if (typeof window.loadChatRooms === "function") window.loadChatRooms();
        localStorage.removeItem(`chatHistory_${newRoomId}`);

        // ② 最初のメッセージ
        const firstMsg = setupInfo
          ? `【タスク】${taskName}\n【状況・作業環境】${setupInfo}`
          : `【タスク】${taskName}`;

        // ③ Bot 応答生成
        if (typeof window.generateResponse === "function") window.generateResponse(firstMsg, aiModel);
      })
      .catch((err) => {
        isTaskLaunchInProgress = false;
        alert("チャットルーム作成に失敗: " + err);
      });
  } else {
    isTaskLaunchInProgress = false;
    console.error("createNewChatRoom is not defined");
  }
}
