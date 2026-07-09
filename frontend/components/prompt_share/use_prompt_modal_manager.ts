import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MutableRefObject
} from "react";

import type { ModalKey } from "./prompt_share_page_types";
import { getModalFocusableElements } from "./prompt_share_page_utils";

type UsePromptModalManagerOptions = {
  isPostSubmitting: boolean;
  onCloseDetail: () => void;
  onClosePost: () => void;
  postModalRef: MutableRefObject<HTMLDivElement | null>;
  promptDetailModalRef: MutableRefObject<HTMLDivElement | null>;
  promptShareModalRef: MutableRefObject<HTMLDivElement | null>;
};

// モーダルの開閉、フォーカス復元、スクロールロック、Escape/Tab操作を管理する
// Manages modal open/close state, focus restoration, scroll lock, and Escape/Tab keyboard behavior
export function usePromptModalManager({
  isPostSubmitting,
  onCloseDetail,
  onClosePost,
  postModalRef,
  promptDetailModalRef,
  promptShareModalRef
}: UsePromptModalManagerOptions) {
  const [activeModal, setActiveModal] = useState<ModalKey>(null);
  const activeModalRef = useRef<ModalKey>(null);
  const previousFocusedElementRef = useRef<HTMLElement | null>(null);
  const preferredFocusElementRef = useRef<HTMLElement | null>(null);
  const lockedScrollYRef = useRef(0);
  const hasModalLockRef = useRef(false);

  useEffect(() => {
    activeModalRef.current = activeModal;
  }, [activeModal]);

  // モーダルキーからDOMのref要素へのマッピングを提供する
  // Maps a modal key to its corresponding DOM ref element
  const getModalElement = useCallback((modal: Exclude<ModalKey, null>) => {
    if (modal === "post") return postModalRef.current;
    if (modal === "detail") return promptDetailModalRef.current;
    return promptShareModalRef.current;
  }, [postModalRef, promptDetailModalRef, promptShareModalRef]);

  // モーダル内のフォーカス可能な要素を取得し、優先要素または先頭要素へフォーカスを移す
  // Finds focusable elements inside a modal and moves focus to the preferred or first element
  const focusModal = useCallback(
    (modal: Exclude<ModalKey, null>) => {
      const modalElement = getModalElement(modal);
      if (!modalElement) {
        return;
      }

      const focusableElements = getModalFocusableElements(modalElement);
      const preferredElement = preferredFocusElementRef.current;
      const fallbackTarget =
        modalElement.querySelector<HTMLElement>(".post-modal-content") || modalElement;

      const target =
        (preferredElement && focusableElements.includes(preferredElement) ? preferredElement : null) ||
        focusableElements[0] ||
        fallbackTarget;

      window.requestAnimationFrame(() => {
        target.focus();
      });
    },
    [getModalElement]
  );

  // 指定されたモーダルを閉じ、モーダル種別ごとの状態をクリアする
  // Closes the specified modal and clears modal-specific state
  const closeModal = useCallback(
    (modal: Exclude<ModalKey, null>, options?: { rotateTrigger?: boolean }) => {
      void options;
      if (activeModalRef.current !== modal) {
        return false;
      }

      setActiveModal(null);
      if (modal === "post") {
        onClosePost();
      } else if (modal === "detail") {
        onCloseDetail();
      }
      return true;
    },
    [onCloseDetail, onClosePost]
  );

  // モーダルを開く前にトリガー要素を記録しておき、閉じた後にフォーカスを元の位置へ戻せるようにする
  // Records the trigger element before opening so focus can be restored when the modal closes
  const openModal = useCallback((modal: Exclude<ModalKey, null>, preferredElement?: HTMLElement | null) => {
    previousFocusedElementRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    preferredFocusElementRef.current = preferredElement || null;
    setActiveModal(modal);
  }, []);

  // モーダルの開閉に応じてbodyのスクロールをロック/アンロックし、フォーカスを管理する
  // Locks/unlocks body scroll when modals open/close and manages focus accordingly
  useEffect(() => {
    if (!activeModal) {
      if (!hasModalLockRef.current) {
        previousFocusedElementRef.current = null;
        preferredFocusElementRef.current = null;
        return;
      }
      // モーダルを閉じるときにスクロール位置を復元する
      // Restore the scroll position when closing a modal
      document.documentElement.classList.remove("ps-modal-open");
      document.body.classList.remove("ps-modal-open");
      document.body.style.position = "";
      document.body.style.top = "";
      document.body.style.left = "";
      document.body.style.right = "";
      document.body.style.width = "";
      window.scrollTo(0, lockedScrollYRef.current);
      hasModalLockRef.current = false;

      if (previousFocusedElementRef.current) {
        previousFocusedElementRef.current.focus();
      }
      previousFocusedElementRef.current = null;
      preferredFocusElementRef.current = null;
      return;
    }

    // position: fixed でbodyを固定し、CSSでスクロールバーが消えても幅が変わらないようにする
    // Fixes the body position to prevent scroll while keeping the width stable to avoid layout shift
    if (!document.body.classList.contains("ps-modal-open")) {
      lockedScrollYRef.current = window.scrollY || window.pageYOffset || 0;
      document.documentElement.classList.add("ps-modal-open");
      document.body.classList.add("ps-modal-open");
      document.body.style.position = "fixed";
      document.body.style.top = `-${lockedScrollYRef.current}px`;
      document.body.style.left = "0";
      document.body.style.right = "0";
      document.body.style.width = "100%";
      hasModalLockRef.current = true;
    }

    focusModal(activeModal);
  }, [activeModal, focusModal]);

  // モーダル内でのキーボード操作（Escape・Tabトラップ）を処理してアクセシビリティを確保する
  // Handles keyboard navigation inside modals (Escape to close, Tab trapping for accessibility)
  useEffect(() => {
    if (!activeModal) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      const modalElement = getModalElement(activeModal);
      if (!modalElement) {
        return;
      }

      if (event.key === "Escape") {
        // 投稿送信中はEscapeキーでモーダルを閉じない
        // Prevent closing the modal with Escape while a post submission is in progress
        if (activeModal === "post" && isPostSubmitting) {
          return;
        }
        event.preventDefault();
        closeModal(activeModal);
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      // Tabキーでフォーカスをモーダル内に閉じ込めるフォーカストラップ
      // Focus trap: keeps Tab navigation confined within the modal
      const focusableElements = getModalFocusableElements(modalElement);
      if (focusableElements.length === 0) {
        event.preventDefault();
        const fallback = modalElement.querySelector<HTMLElement>(".post-modal-content");
        fallback?.focus();
        return;
      }

      const firstFocusable = focusableElements[0];
      const lastFocusable = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;

      if (event.shiftKey) {
        if (!activeElement || activeElement === firstFocusable || !modalElement.contains(activeElement)) {
          event.preventDefault();
          lastFocusable.focus();
        }
        return;
      }

      if (!activeElement || activeElement === lastFocusable || !modalElement.contains(activeElement)) {
        event.preventDefault();
        firstFocusable.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [activeModal, closeModal, getModalElement, isPostSubmitting]);

  return {
    activeModal,
    closeModal,
    hasModalLockRef,
    openModal
  };
}
