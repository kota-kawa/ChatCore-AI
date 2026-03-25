import { initPromptShareAuth } from "./auth";
import { createModalController } from "./modal_controller";
import { initPromptCards } from "./prompt_cards";
import { initPromptDetailModal } from "./prompt_detail";
import { initPromptFeed } from "./prompt_feed";
import { initPromptPostForm } from "./post_form";
import { initPromptShareDialog } from "./prompt_share_dialog";

function initPromptSharePage(attempt = 0) {
  // SSR/遅延描画時に備え、必要要素が出るまで短時間リトライする
  // Retry briefly until required DOM appears (for SSR/deferred rendering timing).
  const promptContainer = document.querySelector(".prompt-cards") as HTMLElement | null;
  if (!promptContainer) {
    if (attempt < 10) {
      requestAnimationFrame(() => initPromptSharePage(attempt + 1));
    }
    return;
  }
  if (promptContainer.dataset.psInitialized === "true") {
    // 二重初期化防止
    // Guard against duplicate page initialization.
    return;
  }
  promptContainer.dataset.psInitialized = "true";
  const promptCountMeta = document.getElementById("promptCountMeta") as HTMLElement | null;

  function setPromptCountMeta(text: string) {
    if (!promptCountMeta) return;
    promptCountMeta.textContent = text;
  }

  const openModalBtn = document.getElementById("openPostModal");
  const heroOpenModalBtn = document.getElementById("heroOpenPostModal");
  const postModal = document.getElementById("postModal") as HTMLElement | null;
  const closeModalBtn = document.querySelector("#postModal .close-btn") as HTMLButtonElement | null;
  const postModalTitleInput = document.getElementById("prompt-title") as HTMLInputElement | null;
  const newPromptIcon = openModalBtn ? openModalBtn.querySelector("i") : null;

  const modalController = createModalController(postModal);
  const openModal = modalController.openModal;
  const closeModal = modalController.closeModal;

  // 新規投稿アイコンの回転アニメーションを毎回確実に再トリガーする
  // Force-restart the compose icon animation on each trigger.
  const triggerNewPromptIconRotation = () => {
    if (!newPromptIcon) {
      return;
    }
    newPromptIcon.classList.remove("rotating");
    void (newPromptIcon as HTMLElement).offsetWidth;
    newPromptIcon.classList.add("rotating");
  };

  if (newPromptIcon) {
    newPromptIcon.addEventListener("animationend", () => {
      newPromptIcon.classList.remove("rotating");
    });
  }

  let hasAutoFilledAuthor = false;
  const authState = initPromptShareAuth({
    getHasAutoFilledAuthor: () => hasAutoFilledAuthor,
    setHasAutoFilledAuthor: (value) => {
      hasAutoFilledAuthor = value;
    }
  });

  const promptShareDialog = initPromptShareDialog({
    openModal,
    closeModal: (modal) => {
      closeModal(modal);
    }
  });
  const promptDetailModal = initPromptDetailModal({
    openModal,
    closeModal: (modal) => {
      closeModal(modal);
    }
  });

  const promptCards = initPromptCards({
    promptContainer,
    setPromptCountMeta,
    getIsLoggedIn: () => authState.isLoggedIn(),
    onOpenPromptShareDialog: (prompt, event) => promptShareDialog.openPromptShareDialog(prompt, event),
    onShowPromptDetailModal: (prompt) => promptDetailModal.showPromptDetailModal(prompt)
  });

  const promptFeed = initPromptFeed({
    promptContainer,
    setPromptCountMeta,
    renderPromptCards: promptCards.renderPromptCards,
    renderPromptStatusMessage: promptCards.renderPromptStatusMessage
  });

  const postFormState = initPromptPostForm({
    loadPrompts: promptFeed.loadPrompts,
    closeModal: (modal, options) => {
      const closed = closeModal(modal);
      if (closed && options?.rotateTrigger) {
        triggerNewPromptIconRotation();
      }
    },
    setHasAutoFilledAuthor: (value) => {
      hasAutoFilledAuthor = value;
    }
  });

  modalController.setPostSubmissionStateProvider(() => ({
    isPostSubmitting: postFormState.getIsPostSubmitting(),
    resetPostModalState: postFormState.resetPostModalState
  }));

  const openComposerModal = () => {
    if (!postModal) return;
    // 投稿機能は認証必須
    // Posting prompts requires authenticated user state.
    if (!authState.isLoggedIn()) {
      alert("プロンプトを投稿するにはログインが必要です。");
      return;
    }

    triggerNewPromptIconRotation();
    postFormState.setPromptPostStatus("カテゴリやタイトルを軽く入れてから AI 補助を使うと、提案が安定します。");
    openModal(postModal, postModalTitleInput);
  };

  if (openModalBtn && postModal) {
    openModalBtn.addEventListener("click", openComposerModal);
  }

  if (heroOpenModalBtn && postModal) {
    heroOpenModalBtn.addEventListener("click", openComposerModal);
  }

  if (closeModalBtn && postModal) {
    closeModalBtn.addEventListener("click", function () {
      const closed = closeModal(postModal);
      if (closed) {
        triggerNewPromptIconRotation();
      }
    });
  }

  // 投稿モーダルは背景クリックでは閉じない（×ボタンのみ）
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => initPromptSharePage());
} else {
  initPromptSharePage();
}

export {};
