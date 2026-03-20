// Task title updater

function updateTaskTitle(card: HTMLElement, newTitle: string) {
  const truncatedTitle = newTitle;

  // 既存のヘッダーがある場合はテキストだけを更新
  const header = card.querySelector<HTMLElement>(".task-header");
  if (header) {
    header.textContent = truncatedTitle;
  } else if (typeof window.loadTaskCards === "function") {
    // ヘッダーが存在しない異常状態では一覧を再描画して整える
    window.loadTaskCards();
    return;
  }

  // 過去に生成された task-title 要素が残っている場合は削除しておく
  card.querySelectorAll(".task-title").forEach((elem) => elem.remove());
}

// Task edit modal

function showModal(modalEl: HTMLElement | null) {
  if (!modalEl) return;
  modalEl.style.display = "flex";
}

function hideModal(modalEl: HTMLElement | null) {
  if (!modalEl) return;
  modalEl.style.display = "none";
}

const initTaskManager = () => {
  const modalEl = document.getElementById("taskEditModal");
  const closeBtn = document.getElementById("closeTaskEditModal");
  const cancelBtn = document.getElementById("cancelTaskEditModal");
  const saveBtn = document.getElementById("saveTaskChanges");

  // モーダルの閉じる操作
  closeBtn?.addEventListener("click", () => hideModal(modalEl));
  cancelBtn?.addEventListener("click", () => hideModal(modalEl));

  if (!saveBtn) return;

  saveBtn.addEventListener("click", () => {
    const taskNameEl = document.getElementById("taskName") as HTMLInputElement | null;
    const promptTemplateEl = document.getElementById("promptTemplate") as HTMLTextAreaElement | null;
    const responseRulesEl = document.getElementById("responseRules") as HTMLTextAreaElement | null;
    const outputSkeletonEl = document.getElementById("outputSkeleton") as HTMLTextAreaElement | null;
    const inputExamplesEl = document.getElementById("inputExamples") as HTMLTextAreaElement | null;
    const outputExamplesEl = document.getElementById("outputExamples") as HTMLTextAreaElement | null;
    if (
      !taskNameEl ||
      !promptTemplateEl ||
      !responseRulesEl ||
      !outputSkeletonEl ||
      !inputExamplesEl ||
      !outputExamplesEl
    ) {
      alert("入力欄が見つかりませんでした。");
      return;
    }

    // 1. モーダル内の入力値取得
    const taskName = taskNameEl.value.trim();
    const promptTemplate = promptTemplateEl.value.trim();
    const responseRules = responseRulesEl.value.trim();
    const outputSkeleton = outputSkeletonEl.value.trim();
    const inputExamples = inputExamplesEl.value.trim();
    const outputExamples = outputExamplesEl.value.trim();

    // 2. 編集前のタスク名を dataset から取得
    const editingCard = window.currentEditingCard;
    if (!editingCard) {
      alert("編集対象が見つかりませんでした。");
      return;
    }
    const oldTask = editingCard.dataset.task;
    if (!oldTask) {
      alert("編集対象のタスク情報が見つかりませんでした。");
      return;
    }

    // 3. サーバー送信用ペイロード
    const payload = {
      old_task: oldTask,
      new_task: taskName,
      prompt_template: promptTemplate,
      response_rules: responseRules,
      output_skeleton: outputSkeleton,
      input_examples: inputExamples,
      output_examples: outputExamples
    };

    // 4. API 呼び出し
    fetch("/api/edit_task", {
      method: "POST",
      credentials: "same-origin", // Cookie を送信
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then((response) => {
        const ct = response.headers.get("Content-Type") || "";
        if (ct.includes("application/json")) {
          // 正常 or JSON エラー(JSON.stringify された {"error":...})
          return response.json().then((data) => {
            if (!response.ok) throw new Error(data.error || "更新に失敗しました");
            return data;
          });
        } else {
          // HTML の 500 ページなどが返ってきた場合
          return response.text().then((text) => {
            console.error("非JSONレスポンス:", text);
            throw new Error(`サーバーエラー: ${response.status}`);
          });
        }
      })
      .then(() => {
        // 5. 成功したら data- 属性を更新
        const card = editingCard;
        card.dataset.task = taskName;
        card.dataset.prompt_template = promptTemplate;
        card.dataset.response_rules = responseRules;
        card.dataset.output_skeleton = outputSkeleton;
        card.dataset.input_examples = inputExamples;
        card.dataset.output_examples = outputExamples;
        if (window.invalidateTasksCache) window.invalidateTasksCache();

        // 6. タイトルを書き換え
        updateTaskTitle(card, taskName);

        // 7. モーダル閉じる
        hideModal(modalEl);
      })
      .catch((error) => {
        alert("更新に失敗しました: " + error.message);
        console.error("edit_task error:", error);
      });
  });
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initTaskManager);
} else {
  initTaskManager();
}

// Task ordering and editing

let isEditingOrder = false;
let editButton: HTMLButtonElement | null;
let draggingTask: HTMLElement | null = null;
let taskPlaceholder: HTMLElement | null = null;
let taskOffsetX = 0;
let taskOffsetY = 0;

// タスクカード読み込み後に並び替え編集ボタンを追加する処理
function initTaskOrderEditing() {
  if (!window.loggedIn) return; // ★ 未ログインなら何もしない

  // ヘッダー要素を取得
  const header = document.querySelector(".task-selection-header");
  if (!header) return;

  // 既存のボタンがあれば削除
  if (editButton) editButton.remove();

  // ボタン作成
  editButton = document.createElement("button");
  editButton.id = "edit-task-order-btn";
  editButton.className = "primary-button";
  // インライン表示に合わせるため余白は不要
  editButton.style.margin = "0";
  editButton.type = "button"; // フォーム送信を防止
  // Bootstrapのアイコンをセット（ここでは例としてbi-arrows-moveを使用）
  editButton.innerHTML = '<i class="bi bi-arrows-move"></i>';
  editButton.title = "並び替え編集"; // ツールチップ用

  editButton.addEventListener("click", toggleTaskOrderEditing);
  // ヘッダー内にボタンを追加
  header.appendChild(editButton);
}

// 編集モードの ON/OFF 切替
function toggleTaskOrderEditing() {
  // 編集モードをトグルする
  isEditingOrder = !isEditingOrder;
  window.isEditingOrder = isEditingOrder;

  if (isEditingOrder) {
    // 編集モード開始時：
    // ボタンを押した瞬間にアイコンをチェックマークに変更し、タイトルを「完了」にする
    if (editButton) {
      editButton.title = "完了";
      editButton.innerHTML = '<i class="bi bi-check"></i>';
    }

    // タスクカード表示の設定やドラッグ＆ドロップを有効化
    document.querySelectorAll<HTMLElement>(".task-selection .prompt-card").forEach((card) => {
      card.style.display = "flex";
      card.style.position = "relative";
    });
    const toggleBtn = document.getElementById("toggle-tasks-btn");
    if (toggleBtn) {
      toggleBtn.style.display = "none";
    }
    enableTaskDragAndDrop();

    document.querySelectorAll<HTMLElement>(".prompt-card").forEach((card) => {
      // 既にボタンが存在する場合は削除（念のため）
      const existingDeleteContainer = card.querySelector(".delete-container");
      const existingEditContainer = card.querySelector(".edit-container");
      if (existingDeleteContainer) existingDeleteContainer.remove();
      if (existingEditContainer) existingEditContainer.remove();

      // 削除ボタンコンテナ（左上・カード外側に配置）
      const deleteContainer = document.createElement("div");
      deleteContainer.className = "delete-container";
      deleteContainer.style.position = "absolute";
      deleteContainer.style.top = "-10px";
      deleteContainer.style.left = "-10px";
      deleteContainer.style.zIndex = "10";

      // 削除ボタン
      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button"; // 追加：フォーム送信を防ぐ
      deleteBtn.className = "card-delete-btn";
      deleteBtn.style.width = "24px";
      deleteBtn.style.height = "24px";
      deleteBtn.style.borderRadius = "50%";
      deleteBtn.style.border = "none";
      deleteBtn.style.backgroundColor = "#dc3545";
      deleteBtn.style.color = "white";
      deleteBtn.style.fontSize = "14px";
      deleteBtn.style.display = "flex";
      deleteBtn.style.alignItems = "center";
      deleteBtn.style.justifyContent = "center";
      deleteBtn.innerHTML = '<i class="bi bi-trash"></i>';
      // ボタン押下時にタスクカードのクリックイベントと区別するためイベント伝播を停止
      deleteBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        const targetCard = (e.currentTarget as HTMLElement | null)?.closest(".prompt-card") as HTMLElement | null;
        if (!targetCard) return;
        if (confirm("このタスクを削除してもよろしいですか？")) {
          const taskName = targetCard.getAttribute("data-task");
          fetch("/api/delete_task", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ task: taskName })
          })
            .then((response) => {
              if (!response.ok) {
                return response.json().then((errorData) => {
                  throw new Error(errorData.error || "削除に失敗しました");
                });
              }
              return response.json();
            })
            .then(() => {
              // 削除が成功した場合、対応するラッパー要素を削除し、並び順保存のためのAPI呼び出しも非同期で行う
              const wrapper = targetCard.closest(".task-wrapper");
              if (wrapper) {
                wrapper.remove();
              }
              if (window.invalidateTasksCache) window.invalidateTasksCache();
              // 並び順の更新は非同期で行うので、ここでページ再読み込みは行わずにDOM上を更新
              saveTaskOrder();
            })
            .catch((err) => {
              alert("削除に失敗しました: " + err.message);
            });
        }
      });

      // 削除ボタン用ツールチップ
      const deleteTooltip = document.createElement("span");
      deleteTooltip.textContent = "削除";
      deleteTooltip.style.position = "absolute";
      deleteTooltip.style.bottom = "100%";
      deleteTooltip.style.left = "50%";
      deleteTooltip.style.transform = "translateX(-50%)";
      deleteTooltip.style.marginBottom = "4px";
      deleteTooltip.style.backgroundColor = "rgba(0, 0, 0, 0.75)";
      deleteTooltip.style.color = "white";
      deleteTooltip.style.padding = "2px 4px";
      deleteTooltip.style.borderRadius = "4px";
      deleteTooltip.style.fontSize = "10px";
      deleteTooltip.style.whiteSpace = "nowrap";
      deleteTooltip.style.opacity = "0";
      deleteTooltip.style.transition = "opacity 0.2s";

      // ホバー時の挙動（削除ボタン）
      deleteContainer.addEventListener("mouseenter", () => {
        deleteTooltip.style.opacity = "1";
        deleteBtn.style.transform = "scale(1.1)";
      });
      deleteContainer.addEventListener("mouseleave", () => {
        deleteTooltip.style.opacity = "0";
        deleteBtn.style.transform = "";
      });

      deleteContainer.appendChild(deleteBtn);
      deleteContainer.appendChild(deleteTooltip);

      // 編集ボタンコンテナ（右上・カード外側に配置）
      const editContainer = document.createElement("div");
      editContainer.className = "edit-container";
      editContainer.style.position = "absolute";
      editContainer.style.top = "-10px";
      editContainer.style.right = "-10px";
      editContainer.style.zIndex = "10";

      // 編集ボタン
      const editBtn = document.createElement("button");
      editBtn.type = "button"; // 追加：フォーム送信を防ぐ
      editBtn.className = "card-edit-btn";
      editBtn.style.width = "24px";
      editBtn.style.height = "24px";
      editBtn.style.borderRadius = "50%";
      editBtn.style.border = "none";
      editBtn.style.backgroundColor = "#007bff";
      editBtn.style.color = "white";
      editBtn.style.fontSize = "14px";
      editBtn.style.display = "flex";
      editBtn.style.alignItems = "center";
      editBtn.style.justifyContent = "center";
      editBtn.innerHTML = '<i class="bi bi-pencil"></i>';

      // 編集ボタン押下時の処理
      editBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        const targetCard = (e.currentTarget as HTMLElement | null)?.closest(".prompt-card") as HTMLElement | null;
        if (!targetCard) return;

        // 対象カードの data 属性から値を取得してモーダルのフォームにセット
        window.currentEditingCard = targetCard;
        const taskNameEl = document.getElementById("taskName") as HTMLInputElement | null;
        const promptTemplateEl = document.getElementById("promptTemplate") as HTMLTextAreaElement | null;
        const responseRulesEl = document.getElementById("responseRules") as HTMLTextAreaElement | null;
        const outputSkeletonEl = document.getElementById("outputSkeleton") as HTMLTextAreaElement | null;
        const inputExamplesEl = document.getElementById("inputExamples") as HTMLTextAreaElement | null;
        const outputExamplesEl = document.getElementById("outputExamples") as HTMLTextAreaElement | null;
        if (taskNameEl) taskNameEl.value = targetCard.getAttribute("data-task") || "";
        if (promptTemplateEl) promptTemplateEl.value = targetCard.getAttribute("data-prompt_template") || "";
        if (responseRulesEl) responseRulesEl.value = targetCard.getAttribute("data-response_rules") || "";
        if (outputSkeletonEl) outputSkeletonEl.value = targetCard.getAttribute("data-output_skeleton") || "";
        if (inputExamplesEl) inputExamplesEl.value = targetCard.getAttribute("data-input_examples") || "";
        if (outputExamplesEl) outputExamplesEl.value = targetCard.getAttribute("data-output_examples") || "";

        // カスタムモーダルを表示
        showModal(document.getElementById("taskEditModal"));
      });

      // 編集ボタン用ツールチップ
      const editTooltip = document.createElement("span");
      editTooltip.textContent = "編集";
      editTooltip.style.position = "absolute";
      editTooltip.style.bottom = "100%";
      editTooltip.style.left = "50%";
      editTooltip.style.transform = "translateX(-50%)";
      editTooltip.style.marginBottom = "4px";
      editTooltip.style.backgroundColor = "rgba(0, 0, 0, 0.75)";
      editTooltip.style.color = "white";
      editTooltip.style.padding = "2px 4px";
      editTooltip.style.borderRadius = "4px";
      editTooltip.style.fontSize = "10px";
      editTooltip.style.whiteSpace = "nowrap";
      editTooltip.style.opacity = "0";
      editTooltip.style.transition = "opacity 0.2s";

      editContainer.addEventListener("mouseenter", () => {
        editTooltip.style.opacity = "1";
        editBtn.style.transform = "scale(1.1)";
      });
      editContainer.addEventListener("mouseleave", () => {
        editTooltip.style.opacity = "0";
        editBtn.style.transform = "";
      });

      editContainer.appendChild(editBtn);
      editContainer.appendChild(editTooltip);

      // カードにボタンコンテナを追加
      card.appendChild(deleteContainer);
      card.appendChild(editContainer);
    });
  } else {
    // 編集モード終了時：各種ボタン要素を削除し、ドラッグ＆ドロップを無効化
    document.querySelectorAll(".delete-container").forEach((container) => container.remove());
    document.querySelectorAll(".edit-container").forEach((container) => container.remove());

    disableTaskDragAndDrop();
    saveTaskOrder();

    // 編集モードで変更した表示をリセットし、折り畳みボタンを再生成
    document.querySelectorAll<HTMLElement>(".task-selection .prompt-card").forEach((card) => {
      card.style.display = "";
      card.style.position = "";
    });
    if (typeof window.initToggleTasks === "function") {
      window.initToggleTasks();
    }

    // 画面全体の再読み込みは行わず、必要な部分のみDOMの更新を行う
    // ※もしタスク一覧全体の更新が必要なら、非同期で新たにタスク一覧をfetchして再レンダリングする処理をここに追加

    if (editButton) {
      editButton.title = "並び替え編集";
      editButton.innerHTML = '<i class="bi bi-arrows-move"></i>';
    }
  }
}

// ドラッグ＆ドロップ用イベントを有効化（各カードに .editable クラス追加）
function enableTaskDragAndDrop() {
  const wrappers = document.querySelectorAll<HTMLElement>(".task-wrapper");
  wrappers.forEach((wrapper, index) => {
    wrapper.classList.add("editable"); // ラッパーに追加
    // 内部のカードにも追加
    const card = wrapper.querySelector<HTMLElement>(".prompt-card");
    if (card) {
      card.classList.add("editable");
      // 各カードのアニメーション開始タイミングをずらす（例: 0.1秒刻み）
      card.style.animationDelay = `${index * 0.1}s`;
    }
    wrapper.style.touchAction = "none";
    wrapper.addEventListener("pointerdown", onTaskPointerDown);
  });
}

// イベント解除
function disableTaskDragAndDrop() {
  const wrappers = document.querySelectorAll<HTMLElement>(".task-wrapper");
  wrappers.forEach((wrapper) => {
    wrapper.classList.remove("editable");
    const card = wrapper.querySelector<HTMLElement>(".prompt-card");
    if (card) {
      card.classList.remove("editable");
    }
    wrapper.removeEventListener("pointerdown", onTaskPointerDown);
  });
  document.removeEventListener("pointermove", onTaskPointerMove);
  document.removeEventListener("pointerup", onTaskPointerUp);
  if (draggingTask) {
    draggingTask.style.position = "";
    draggingTask.style.zIndex = "";
  }
}

// pointerdown イベント
function onTaskPointerDown(e: PointerEvent) {
  if (e.button !== 0) return;
  const target = e.target as Element | null;
  if (
    target?.closest(".card-delete-btn") ||
    target?.closest(".card-edit-btn") ||
    target?.closest(".delete-container") ||
    target?.closest(".edit-container")
  ) {
    // 編集・削除ボタンが押された場合は何もせず終了
    return;
  }

  draggingTask = e.currentTarget as HTMLElement | null; // task-wrapper をドラッグ対象にする
  if (!draggingTask) return;
  draggingTask.classList.add("dragging");
  const rect = draggingTask.getBoundingClientRect();

  // 絶対配置に変更
  draggingTask.style.position = "absolute";
  draggingTask.style.width = rect.width + "px";
  draggingTask.style.height = rect.height + "px";
  draggingTask.style.zIndex = "1000";

  const container = document.querySelector(".task-selection") as HTMLElement | null;
  if (!container) return;
  const containerRect = container.getBoundingClientRect();
  draggingTask.style.left = e.clientX - containerRect.left - rect.width / 2 + "px";
  draggingTask.style.top = e.clientY - containerRect.top - rect.height / 2 + "px";

  // プレースホルダーを作成（task-wrapper 用）
  taskPlaceholder = document.createElement("div");
  taskPlaceholder.className = "task-wrapper placeholder";
  taskPlaceholder.style.width = rect.width + "px";
  taskPlaceholder.style.height = rect.height + "px";
  taskPlaceholder.style.border = "1px dashed #aaa";
  container.insertBefore(taskPlaceholder, draggingTask.nextSibling);

  document.addEventListener("pointermove", onTaskPointerMove);
  document.addEventListener("pointerup", onTaskPointerUp);
}

function onTaskPointerMove(e: PointerEvent) {
  if (!draggingTask) return;
  const container = document.querySelector(".task-selection") as HTMLElement | null;
  if (!container) return;
  const containerRect = container.getBoundingClientRect();
  const cardWidth = draggingTask.offsetWidth;
  const cardHeight = draggingTask.offsetHeight;
  draggingTask.style.left = e.clientX - containerRect.left - cardWidth / 2 + "px";
  draggingTask.style.top = e.clientY - containerRect.top - cardHeight / 2 + "px";

  // プレースホルダーの位置更新（wrapper単位で）
  const wrappers = Array.from(container.querySelectorAll<HTMLElement>(".task-wrapper:not(.dragging)"));
  let placed = false;
  for (let wrapper of wrappers) {
    const rect = wrapper.getBoundingClientRect();
    const centerY = rect.top + rect.height / 2;
    if (e.clientY < centerY) {
      if (taskPlaceholder) {
        container.insertBefore(taskPlaceholder, wrapper);
      }
      placed = true;
      break;
    }
  }
  if (!placed && taskPlaceholder) {
    container.appendChild(taskPlaceholder);
  }
}

function onTaskPointerUp() {
  if (!draggingTask) return;
  const container = document.querySelector(".task-selection");
  if (!container || !taskPlaceholder) return;
  container.insertBefore(draggingTask, taskPlaceholder);
  draggingTask.classList.remove("dragging");
  // スタイルリセット
  draggingTask.style.position = "";
  draggingTask.style.left = "";
  draggingTask.style.top = "";
  draggingTask.style.width = "";
  draggingTask.style.height = "";
  draggingTask.style.zIndex = "";
  taskPlaceholder.remove();
  taskPlaceholder = null;
  draggingTask = null;
  document.removeEventListener("pointermove", onTaskPointerMove);
  document.removeEventListener("pointerup", onTaskPointerUp);
}

// 並び順をサーバーに保存する関数
function saveTaskOrder() {
  const wrappers = document.querySelectorAll<HTMLElement>(".task-wrapper");
  const newOrder = Array.from(wrappers)
    .map((wrapper) => {
      const card = wrapper.querySelector<HTMLElement>(".prompt-card");
      if (!card || card.dataset.is_default === "true") {
        return null;
      }
      return card.getAttribute("data-task");
    })
    .filter(Boolean);

  if (newOrder.length === 0) {
    return;
  }

  fetch("/api/update_tasks_order", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ order: newOrder })
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.error) {
        alert("並び順の保存に失敗: " + data.error);
      } else if (window.invalidateTasksCache) {
        window.invalidateTasksCache();
      }
    })
    .catch((err) => {
      alert("並び順の保存に失敗: " + err.toString());
    });
}

// エクスポート（他のスクリプトから利用できるように）
window.initTaskOrderEditing = initTaskOrderEditing;

export {};
