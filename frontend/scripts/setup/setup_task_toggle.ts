import { scheduleSetupViewportFit } from "./setup_viewport";

export function initToggleTasks() {
  const container = document.querySelector<HTMLElement>(".task-selection");
  if (!container) return;
  const oldBtn = document.getElementById("toggle-tasks-btn");
  if (oldBtn) oldBtn.remove();

  const cards = [...container.querySelectorAll<HTMLElement>(".prompt-card")];

  // 以前の inline 指定が残っていても CSS クラス制御を優先する
  cards.forEach((card) => {
    if (card.style.display) card.style.removeProperty("display");
  });

  container.classList.remove("tasks-expanded");

  if (cards.length <= 6) {
    container.classList.remove("tasks-collapsed");
    scheduleSetupViewportFit();
    return;
  }

  container.classList.add("tasks-collapsed");

  // ボタン生成
  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "toggle-tasks-btn";
  btn.className = "primary-button";
  btn.style.width = "100%";
  btn.style.marginTop = "0.1rem";

  let expanded = false;
  const applyExpandedState = () => {
    container.classList.toggle("tasks-expanded", expanded);
    btn.innerHTML = expanded ? '<i class="bi bi-chevron-up"></i> 閉じる' : '<i class="bi bi-chevron-down"></i> もっと見る';
  };

  btn.addEventListener("click", (e) => {
    e.preventDefault();
    expanded = !expanded;
    applyExpandedState();
  });
  applyExpandedState();

  // ボタンをリストの末尾に追加
  const selectionContainer = window.taskSelection || container;
  selectionContainer.appendChild(btn);
  scheduleSetupViewportFit();
}
