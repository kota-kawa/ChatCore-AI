const SETUP_FIT_COMPACT_CLASS = "setup-fit-compact";
const SETUP_FIT_TIGHT_CLASS = "setup-fit-tight";

let setupFitRafId: number | null = null;
let setupViewportFitBound = false;

function applySetupViewportFit() {
  const setupContainer = document.getElementById("setup-container");
  const shell = document.querySelector<HTMLElement>(".chat-page-shell");
  if (!setupContainer || !shell) return;

  const activeElement = document.activeElement as HTMLElement | null;
  const isEditingWithinSetup =
    !!activeElement &&
    setupContainer.contains(activeElement) &&
    activeElement.matches("input, textarea, select, [contenteditable='true']");

  // 入力中は virtual keyboard による viewport 変化でボタンやカードが縮まないよう、現状サイズを維持する
  if (isEditingWithinSetup) {
    return;
  }

  // セットアップ画面非表示時は密度調整クラスを解除しておく
  if (setupContainer.style.display === "none") {
    setupContainer.classList.remove(SETUP_FIT_COMPACT_CLASS, SETUP_FIT_TIGHT_CLASS);
    return;
  }

  const taskSelection = setupContainer.querySelector<HTMLElement>("#task-selection");
  // 「もっと見る」でタスクを展開中は、その時点の密度設定を維持してカードサイズを変えない
  if (taskSelection?.classList.contains("tasks-expanded")) {
    return;
  }

  setupContainer.classList.remove(SETUP_FIT_COMPACT_CLASS, SETUP_FIT_TIGHT_CLASS);

  const shellStyles = window.getComputedStyle(shell);
  const shellPaddingTop = Number.parseFloat(shellStyles.paddingTop) || 0;
  const shellPaddingBottom = Number.parseFloat(shellStyles.paddingBottom) || 0;
  const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
  const availableHeight = Math.max(0, viewportHeight - shellPaddingTop - shellPaddingBottom);

  // Measure the untransformed layout height via scrollHeight rather than
  // getBoundingClientRect(). While returning from the chat view to the setup
  // view, the card is still mid-transition (3D scale/translate + blur driven by
  // the data-view animation), so getBoundingClientRect() would report the
  // visually scaled-down height and make the density decision flicker.
  // scrollHeight is unaffected by transforms, so the correct fit class is
  // chosen on the first pass.
  //
  // offsetHeight would look tempting here, but at narrow widths
  // .chat-page-stage switches to place-items: stretch, which clamps the
  // container's layout box (and therefore offsetHeight) to the viewport
  // height regardless of how tall its content actually is. That made this
  // overflow check permanently false on mobile, so the compact/tight density
  // classes never applied and overflowing content (including the "view past
  // chats" button) silently fell back to internal scrolling instead of being
  // shrunk to fit. scrollHeight still reports the true content height even
  // when the box itself is clamped, since #setup-container scrolls its own
  // overflow on mobile.
  if (setupContainer.scrollHeight <= availableHeight + 1) return;

  setupContainer.classList.add(SETUP_FIT_COMPACT_CLASS);
  if (setupContainer.scrollHeight <= availableHeight + 1) return;

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
