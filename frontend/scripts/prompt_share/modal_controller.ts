export type ModalController = {
  openModal: (modal: HTMLElement, preferredElement?: HTMLElement | null) => void;
  closeModal: (modal: HTMLElement) => boolean;
  setPostSubmissionStateProvider: (
    provider: () => { isPostSubmitting: boolean; resetPostModalState: () => void }
  ) => void;
};

export function createModalController(postModal: HTMLElement | null): ModalController {
  let activeModal: HTMLElement | null = null;
  let previouslyFocusedElement: HTMLElement | null = null;
  let lockedScrollY = 0;
  let postStateProvider: (() => {
    isPostSubmitting: boolean;
    resetPostModalState: () => void;
  }) | null = null;

  function getModalFocusableElements(modal: HTMLElement) {
    const selector = [
      "a[href]",
      "area[href]",
      "button:not([disabled])",
      "input:not([disabled])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      "[tabindex]:not([tabindex='-1'])"
    ].join(", ");

    return Array.from(modal.querySelectorAll<HTMLElement>(selector)).filter((element) => {
      const style = window.getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden";
    });
  }

  function focusModal(modal: HTMLElement, preferredElement?: HTMLElement | null) {
    const fallbackTarget =
      modal.querySelector<HTMLElement>(".post-modal-content") || (modal as HTMLElement);
    const focusableElements = getModalFocusableElements(modal);
    const target =
      (preferredElement && getModalFocusableElements(modal).includes(preferredElement)
        ? preferredElement
        : null) ||
      focusableElements[0] ||
      fallbackTarget;

    window.requestAnimationFrame(() => {
      target.focus();
    });
  }

  function lockBackgroundInteraction() {
    if (document.body.classList.contains("ps-modal-open")) {
      return;
    }

    lockedScrollY = window.scrollY || window.pageYOffset || 0;
    document.documentElement.classList.add("ps-modal-open");
    document.body.classList.add("ps-modal-open");
    document.body.style.position = "fixed";
    document.body.style.top = `-${lockedScrollY}px`;
    document.body.style.left = "0";
    document.body.style.right = "0";
    document.body.style.width = "100%";
  }

  function unlockBackgroundInteraction() {
    document.documentElement.classList.remove("ps-modal-open");
    document.body.classList.remove("ps-modal-open");
    document.body.style.position = "";
    document.body.style.top = "";
    document.body.style.left = "";
    document.body.style.right = "";
    document.body.style.width = "";
    window.scrollTo(0, lockedScrollY);
  }

  function openModal(modal: HTMLElement, preferredElement?: HTMLElement | null) {
    previouslyFocusedElement = document.activeElement as HTMLElement | null;
    activeModal = modal;
    modal.classList.add("show");
    modal.setAttribute("aria-hidden", "false");
    lockBackgroundInteraction();
    focusModal(modal, preferredElement);
  }

  function closeModal(modal: HTMLElement) {
    if (!modal.classList.contains("show")) {
      return false;
    }

    modal.classList.remove("show");
    modal.setAttribute("aria-hidden", "true");
    if (modal === postModal && postStateProvider) {
      postStateProvider().resetPostModalState();
    }

    if (activeModal === modal) {
      activeModal = null;
    }

    const hasVisibleModal = Boolean(document.querySelector(".post-modal.show"));
    if (!hasVisibleModal) {
      unlockBackgroundInteraction();
      if (previouslyFocusedElement) {
        previouslyFocusedElement.focus();
      }
      previouslyFocusedElement = null;
    }
    return true;
  }

  function handleModalKeydown(event: KeyboardEvent) {
    if (!activeModal || !activeModal.classList.contains("show")) {
      return;
    }

    if (event.key === "Escape") {
      const isPostSubmitting = postStateProvider?.().isPostSubmitting || false;
      if (activeModal === postModal && isPostSubmitting) {
        return;
      }
      event.preventDefault();
      closeModal(activeModal);
      return;
    }

    if (event.key !== "Tab") {
      return;
    }

    const focusableElements = getModalFocusableElements(activeModal);
    if (focusableElements.length === 0) {
      event.preventDefault();
      const fallback = activeModal.querySelector<HTMLElement>(".post-modal-content");
      fallback?.focus();
      return;
    }

    const firstFocusable = focusableElements[0];
    const lastFocusable = focusableElements[focusableElements.length - 1];
    const currentElement = document.activeElement as HTMLElement | null;

    if (event.shiftKey) {
      if (!currentElement || currentElement === firstFocusable || !activeModal.contains(currentElement)) {
        event.preventDefault();
        lastFocusable.focus();
      }
      return;
    }

    if (!currentElement || currentElement === lastFocusable || !activeModal.contains(currentElement)) {
      event.preventDefault();
      firstFocusable.focus();
    }
  }

  if (document.body && document.body.dataset.psModalKeydownListener !== "true") {
    document.body.dataset.psModalKeydownListener = "true";
    document.addEventListener("keydown", handleModalKeydown);
  }

  return {
    openModal,
    closeModal,
    setPostSubmissionStateProvider(provider) {
      postStateProvider = provider;
    }
  };
}
