import { readCachedTasks, writeCachedTasks } from "./setup_tasks_cache";
import { initSetupTaskCards } from "./setup_task_launch";
import { getFallbackTasks, formatMultilineHtml, createTaskSignature } from "./setup_task_utils";
import { initToggleTasks } from "./setup_task_toggle";
import type { LoadTaskCardsOptions, TaskItem } from "./setup_types";
import { scheduleSetupViewportFit } from "./setup_viewport";

function hydrateSSRTaskCards() {
  const container = document.getElementById("task-selection");
  if (!container || container.dataset.tasksSignature) return;

  const hasSSRTaskCards = container.querySelector(".task-wrapper .prompt-card") !== null;
  if (!hasSSRTaskCards) return;

  // SSR で描画済みのデフォルトカードを初期状態として採用し、初回再描画を避ける
  container.dataset.tasksSignature = createTaskSignature(getFallbackTasks());
  initSetupTaskCards();
  initToggleTasks();
  if (typeof window.initTaskOrderEditing === "function") window.initTaskOrderEditing();
  scheduleSetupViewportFit();
}

export function loadTaskCards(options: LoadTaskCardsOptions = {}) {
  const forceRefresh = Boolean(options.forceRefresh);
  const ioModal = document.getElementById("io-modal");
  const ioModalContent = document.getElementById("io-modal-content");
  const taskSelection = document.getElementById("task-selection");

  // モーダルを閉じるヘルパ
  function closeIOModal() {
    if (!ioModal) return;
    ioModal.style.display = "none";
    ioModal.setAttribute("aria-hidden", "true");
  }

  if (ioModal && ioModalContent && !ioModal.dataset.bound) {
    ioModal.dataset.bound = "true";
    ioModal.setAttribute("aria-hidden", "true");
    // 背景クリック or 閉じるボタン押下でモーダルを閉じる
    ioModal.addEventListener(
      "click",
      (e) => {
        const target = e.target as Element | null;
        if (!target) return;
        if (target === ioModal || target.closest("[data-close-task-detail]")) {
          closeIOModal();
        }
      },
      true
    );
    // 内部クリックでは閉じない
    ioModalContent.addEventListener("click", (e) => e.stopPropagation());
    // ESC キーで閉じる
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (ioModal.style.display === "none") return;
      closeIOModal();
    });
  }

  const openTaskDetailModal = (card: HTMLElement) => {
    if (!ioModal || !ioModalContent) return;
    const safeTask = formatMultilineHtml(card.dataset.task || "タスク名がありません");
    const safePromptTemplate = formatMultilineHtml(card.dataset.prompt_template || "プロンプトテンプレートはありません");
    const responseRules = (card.dataset.response_rules || "").trim();
    const outputSkeleton = (card.dataset.output_skeleton || "").trim();
    const inputExamples = (card.dataset.input_examples || "").trim();
    const outputExamples = (card.dataset.output_examples || "").trim();
    const detailSections = [
      `
        <section class="task-detail-section">
          <h6 class="task-detail-section-title">タスク名</h6>
          <div class="task-detail-section-body task-detail-section-body-compact">${safeTask}</div>
        </section>
      `,
      `
        <section class="task-detail-section">
          <h6 class="task-detail-section-title">プロンプトテンプレート</h6>
          <div class="task-detail-section-body">${safePromptTemplate}</div>
        </section>
      `
    ];

    if (responseRules) {
      detailSections.push(`
        <section class="task-detail-section">
          <h6 class="task-detail-section-title">回答ルール</h6>
          <div class="task-detail-section-body">${formatMultilineHtml(responseRules)}</div>
        </section>
      `);
    }

    if (outputSkeleton) {
      detailSections.push(`
        <section class="task-detail-section">
          <h6 class="task-detail-section-title">出力テンプレート</h6>
          <div class="task-detail-section-body">${formatMultilineHtml(outputSkeleton)}</div>
        </section>
      `);
    }

    if (inputExamples) {
      detailSections.push(`
        <section class="task-detail-section">
          <h6 class="task-detail-section-title">入力例</h6>
          <div class="task-detail-section-body">${formatMultilineHtml(inputExamples)}</div>
        </section>
      `);
    }

    if (outputExamples) {
      detailSections.push(`
        <section class="task-detail-section">
          <h6 class="task-detail-section-title">出力例</h6>
          <div class="task-detail-section-body">${formatMultilineHtml(outputExamples)}</div>
        </section>
      `);
    }

    if (!responseRules && !outputSkeleton && !inputExamples && !outputExamples) {
      detailSections.push(`
        <section class="task-detail-section">
          <h6 class="task-detail-section-title">補助情報</h6>
          <div class="task-detail-section-body">追加の回答ルールや例は設定されていません。</div>
        </section>
      `);
    }

    ioModalContent.innerHTML = `
      <div class="task-detail-modal-shell">
        <div class="task-detail-modal-header">
          <div>
            <p class="task-detail-modal-eyebrow">Task Detail</p>
            <h5 class="task-detail-modal-title" id="taskDetailTitle">タスク詳細</h5>
          </div>
          <button type="button" class="task-detail-modal-close" data-close-task-detail aria-label="タスク詳細を閉じる">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
        <div class="task-detail-sections">
          ${detailSections.join("")}
        </div>
      </div>`;
    ioModal.style.display = "flex";
    ioModal.setAttribute("aria-hidden", "false");
    ioModal.focus();
  };

  if (taskSelection && !taskSelection.dataset.detailBound) {
    taskSelection.dataset.detailBound = "true";
    taskSelection.addEventListener("click", (e) => {
      const target = e.target as Element | null;
      const detailButton = target?.closest(".task-detail-toggle");
      if (!detailButton) return;
      e.preventDefault();
      e.stopPropagation();
      const card = detailButton.closest(".prompt-card") as HTMLElement | null;
      if (!card) return;
      openTaskDetailModal(card);
    });
  }

  const renderTaskCards = (tasks: TaskItem[]) => {
    const container = document.getElementById("task-selection");
    if (!container) return;
    const signature = createTaskSignature(tasks);

    // 同一内容の再描画は避け、遅延後の「全体再表示」を抑える
    if (container.dataset.tasksSignature === signature) return;
    container.dataset.tasksSignature = signature;

    // コンテナをクリア
    container.innerHTML = "";

    // タスクが空の場合はメッセージを表示
    if (!tasks || tasks.length === 0) {
      container.innerHTML = "<p>タスクが見つかりませんでした。</p>";
      return;
    }

    tasks.forEach((task) => {
      // task自体がnull/undefinedの場合はスキップ（念のため）
      if (!task) return;

      const taskName =
        typeof task.name === "string" && task.name.trim()
          ? task.name.trim()
          : task.name
            ? String(task.name)
            : "無題";

      // ラッパー
      const wrapper = document.createElement("div");
      wrapper.className = "task-wrapper";

      // カード
      const card = document.createElement("div");
      card.className = "prompt-card";
      card.dataset.task = taskName;
      card.dataset.prompt_template = task.prompt_template || "プロンプトテンプレートはありません";
      card.dataset.response_rules = task.response_rules || "";
      card.dataset.output_skeleton = task.output_skeleton || "";
      card.dataset.input_examples = task.input_examples || "";
      card.dataset.output_examples = task.output_examples || "";
      card.dataset.is_default = task.is_default ? "true" : "false";

      // ヘッダー（タイトル＋▼ボタン）
      const headerContainer = document.createElement("div");
      headerContainer.className = "header-container";

      const header = document.createElement("div");
      header.className = "task-header";
      header.textContent = taskName;

      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.classList.add("btn", "btn-outline-success", "btn-md", "task-detail-toggle");
      toggleBtn.innerHTML = '<i class="bi bi-caret-down"></i>';

      headerContainer.append(header, toggleBtn);
      card.appendChild(headerContainer);
      wrapper.appendChild(card);
      container.appendChild(wrapper);
    });

    // クリック／並び替え関係の初期化
    initSetupTaskCards();
    initToggleTasks();
    if (typeof window.initTaskOrderEditing === "function") window.initTaskOrderEditing();
    scheduleSetupViewportFit();
  };

  const applyTasks = (tasks: TaskItem[]) => {
    // タスクが空、もしくは配列でない場合はフォールバックを表示
    if (!Array.isArray(tasks) || tasks.length === 0) {
      renderTaskCards(getFallbackTasks());
      return;
    }
    renderTaskCards(tasks);
  };

  hydrateSSRTaskCards();

  if (!forceRefresh) {
    const cachedTasks = readCachedTasks();
    if (Array.isArray(cachedTasks) && cachedTasks.length > 0) {
      applyTasks(cachedTasks);
      return;
    }
  }

  // 初期ロード時: まずはフォールバックを表示しておく
  renderTaskCards(getFallbackTasks());

  // /api/tasks から取得
  fetch("/api/tasks")
    .then((r) => {
      const contentType = r.headers.get("content-type") || "";
      if (!r.ok) {
        throw new Error(`tasks fetch failed: ${r.status}`);
      }
      if (!contentType.includes("application/json")) {
        throw new Error("tasks response is not json");
      }
      return r.json();
    })
    .then((data) => {
      const tasks: TaskItem[] = Array.isArray(data?.tasks) ? data.tasks : [];
      if (tasks.length > 0) {
        writeCachedTasks(tasks);
      }
      applyTasks(tasks);
    })
    .catch((err) => {
      console.error("タスク読み込みに失敗:", err);
      // エラー時もフォールバックを表示
      applyTasks([]);
    });
}
