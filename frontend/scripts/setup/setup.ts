/**
 * setup.ts
 *
 * ■ タスクカードの取得・表示 (loadTaskCards)
 *   - /api/tasks からタスク一覧を取得し、.prompt-card を動的生成
 *   - カード下向きアイコンでタスク詳細モーダル（プロンプトテンプレート／入出力例）を表示
 *
 * ■ セットアップ画面切替 (showSetupForm)
 *   - チャット画面を隠し、セットアップ画面を再表示
 *
 * ■ タスク選択でチャット開始 (handleTaskCardClick)
 *   - 「状況・作業環境」入力＋カードクリックで新規チャットルーム作成
 *   - 最初のメッセージを Bot に投げてチャットを開始
 *
 * ■ 「もっと見る」折り畳み機能 (initToggleTasks)
 *   - タスクが 6 件超えると 7 件目以降を折り畳み、展開／折り畳みボタンを生成
 */

import { initAiModelSelect } from "./setup_ai_model_select";
import { loadTaskCards } from "./setup_task_cards";
import { initSetupTaskCards, resetTaskLaunchInProgress } from "./setup_task_launch";
import { initToggleTasks } from "./setup_task_toggle";
import { invalidateTasksCache } from "./setup_tasks_cache";
import { bindSetupViewportFit, scheduleSetupViewportFit } from "./setup_viewport";

bindSetupViewportFit();

function showSetupForm() {
  const chatContainer = document.getElementById("chat-container");
  const setupContainer = document.getElementById("setup-container");
  const setupInfoElement = document.getElementById("setup-info") as HTMLTextAreaElement | null;

  // セットアップ画面に戻ったら、次のタスク選択を許可する
  resetTaskLaunchInProgress();
  initAiModelSelect();

  if (chatContainer) chatContainer.style.display = "none";
  if (setupContainer) setupContainer.style.display = "block";
  if (setupInfoElement) setupInfoElement.value = "";
  window.closeChatShareModal?.();

  // サイドバーの状態をクリーンアップ
  const sidebar = document.querySelector(".sidebar");
  if (sidebar) {
    sidebar.classList.remove("open");
  }
  document.body.classList.remove("sidebar-visible");

  loadTaskCards();
  scheduleSetupViewportFit();
}

// ---- グローバル公開 -------------------------------------------------------------
window.showSetupForm = showSetupForm;
window.initToggleTasks = initToggleTasks;
window.initSetupTaskCards = initSetupTaskCards;
window.loadTaskCards = loadTaskCards;
window.invalidateTasksCache = invalidateTasksCache;

export {};
