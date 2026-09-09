import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MutableRefObject
} from "react";

import type { ModalKey } from "./prompt_share_page_types";

type UsePromptModalManagerOptions = {
  isEditSaving: boolean;
  isPostSubmitting: boolean;
  onCloseEdit: () => void;
  onCloseDetail: () => void;
  onClosePost: () => void;
  onCloseProfile: () => void;
  editModalRef: MutableRefObject<HTMLDivElement | null>;
  postModalRef: MutableRefObject<HTMLDivElement | null>;
  promptDetailModalRef: MutableRefObject<HTMLDivElement | null>;
  promptShareModalRef: MutableRefObject<HTMLDivElement | null>;
  promptAuthorProfileModalRef: MutableRefObject<HTMLDivElement | null>;
};

// ページ内で同時に 1 つだけ開くモーダルの状態と、背景スクロールのロック、
// 閉じたあとのフォーカス復元を管理する。
// 初期フォーカス・Tab の閉じ込め・Escape は各モーダルが使う ModalShell 側が担うため、
// ここではキーボード操作を扱わない。
// Tracks which single modal is open on the page, locks background scrolling, and restores
// focus after close. Initial focus, Tab trapping and Escape belong to the ModalShell each
// modal renders through, so no keyboard handling lives here.
export function usePromptModalManager({
  isEditSaving,
  isPostSubmitting,
  onCloseEdit,
  onCloseDetail,
  onClosePost,
  onCloseProfile,
  editModalRef,
  postModalRef,
  promptDetailModalRef,
  promptShareModalRef,
  promptAuthorProfileModalRef
}: UsePromptModalManagerOptions) {
  const [activeModal, setActiveModal] = useState<ModalKey>(null);
  const activeModalRef = useRef<ModalKey>(null);
  const previousFocusedElementRef = useRef<HTMLElement | null>(null);
  const lockedScrollYRef = useRef(0);
  const hasModalLockRef = useRef(false);

  // refs は呼び出し元との契約として受け取り続ける（DOM 参照はページ側の他処理が使う）
  // The refs stay part of the contract; other page logic reads the DOM elements through them
  void editModalRef;
  void postModalRef;
  void promptDetailModalRef;
  void promptShareModalRef;
  void promptAuthorProfileModalRef;

  useEffect(() => {
    activeModalRef.current = activeModal;
  }, [activeModal]);

  // 指定されたモーダルを閉じ、モーダル種別ごとの状態をクリアする
  // 送信中・保存中のモーダルは閉じない（ModalShell の Escape 抑止と同じ条件）
  // Closes the specified modal and clears modal-specific state; a submitting / saving
  // modal stays open (the same condition ModalShell uses to block Escape)
  const closeModal = useCallback(
    (modal: Exclude<ModalKey, null>, options?: { rotateTrigger?: boolean }) => {
      void options;
      if (activeModalRef.current !== modal) {
        return false;
      }
      if ((modal === "post" && isPostSubmitting) || (modal === "edit" && isEditSaving)) {
        return false;
      }

      // aria-hidden が反映される前にモーダル外へフォーカスを戻す。
      // React の state 更新後に復元すると、非表示になったモーダル内に
      // フォーカスが一時的に残り、支援技術向けの警告が発生する。
      // Restore focus outside the modal before aria-hidden flips; restoring after the state
      // update would leave focus inside a hidden modal for a moment and trigger AT warnings.
      const previousFocusedElement = previousFocusedElementRef.current;
      if (previousFocusedElement?.isConnected) {
        previousFocusedElement.focus();
      }

      activeModalRef.current = null;
      setActiveModal(null);
      if (modal === "post") {
        onClosePost();
      } else if (modal === "edit") {
        onCloseEdit();
      } else if (modal === "detail") {
        onCloseDetail();
      } else if (modal === "profile") {
        onCloseProfile();
      }
      return true;
    },
    [isEditSaving, isPostSubmitting, onCloseDetail, onCloseEdit, onCloseProfile, onClosePost]
  );

  // モーダルを開く前にトリガー要素を記録しておき、閉じた後にフォーカスを元の位置へ戻せるようにする
  // Records the trigger element before opening so focus can be restored when the modal closes
  const openModal = useCallback((modal: Exclude<ModalKey, null>) => {
    previousFocusedElementRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    activeModalRef.current = modal;
    setActiveModal(modal);
  }, []);

  // モーダルの開閉に応じてbodyのスクロールをロック/アンロックする
  // Locks/unlocks body scroll when modals open/close
  useEffect(() => {
    if (!activeModal) {
      if (!hasModalLockRef.current) {
        previousFocusedElementRef.current = null;
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

      previousFocusedElementRef.current = null;
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
  }, [activeModal]);

  return {
    activeModal,
    closeModal,
    hasModalLockRef,
    openModal
  };
}
