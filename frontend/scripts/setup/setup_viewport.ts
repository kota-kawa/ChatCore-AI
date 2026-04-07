const SETUP_FIT_COMPACT_CLASS = "setup-fit-compact";
const SETUP_FIT_TIGHT_CLASS = "setup-fit-tight";

let setupFitRafId: number | null = null;
let setupViewportFitBound = false;

function applySetupViewportFit() {
  const setupContainer = document.getElementById("setup-container");
  const shell = document.querySelector<HTMLElement>(".chat-page-shell");
  if (!setupContainer || !shell) return;

  // セットアップ画面非表示時は密度調整クラスを解除しておく
  if (setupContainer.style.display === "none") {
    setupContainer.classList.remove(SETUP_FIT_COMPACT_CLASS, SETUP_FIT_TIGHT_CLASS);
    return;
  }

  setupContainer.classList.remove(SETUP_FIT_COMPACT_CLASS, SETUP_FIT_TIGHT_CLASS);

  // 「もっと見る」でタスクを展開中はカードサイズを固定し、密度調整で縮小しない
  const taskSelection = setupContainer.querySelector<HTMLElement>("#task-selection");
  if (taskSelection?.classList.contains("tasks-expanded")) {
    return;
  }

  const shellStyles = window.getComputedStyle(shell);
  const shellPaddingTop = Number.parseFloat(shellStyles.paddingTop) || 0;
  const shellPaddingBottom = Number.parseFloat(shellStyles.paddingBottom) || 0;
  const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
  const availableHeight = Math.max(0, viewportHeight - shellPaddingTop - shellPaddingBottom);

  if (setupContainer.getBoundingClientRect().height <= availableHeight + 1) return;

  setupContainer.classList.add(SETUP_FIT_COMPACT_CLASS);
  if (setupContainer.getBoundingClientRect().height <= availableHeight + 1) return;

  setupContainer.classList.add(SETUP_FIT_TIGHT_CLASS);
}

export function scheduleSetupViewportFit() {
  if (setupFitRafId !== null) {
    window.cancelAnimationFrame(setupFitRafId);
  }
  setupFitRafId = window.requestAnimationFrame(() => {
    setupFitRafId = null;
    applySetupViewportFit();
  });
}

export function bindSetupViewportFit() {
  if (setupViewportFitBound) return;
  setupViewportFitBound = true;

  window.addEventListener("resize", scheduleSetupViewportFit);
  window.visualViewport?.addEventListener("resize", scheduleSetupViewportFit);
  document.addEventListener("authstatechange", scheduleSetupViewportFit);
}
