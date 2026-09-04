import { useEffect, type Dispatch, type SetStateAction } from "react";

import type { MemoDetail } from "../../lib/memo/types";

type UseMemoPageChromeParams = {
  selectedMemo: MemoDetail | null;
  closeMemoDetail: () => Promise<void>;
  isShareModalOpen: boolean;
  setIsShareModalOpen: Dispatch<SetStateAction<boolean>>;
  isCollectionPanelOpen: boolean;
  setIsCollectionPanelOpen: Dispatch<SetStateAction<boolean>>;
  isExportModalOpen: boolean;
  setIsExportModalOpen: Dispatch<SetStateAction<boolean>>;
};

// ページ全体の副作用（body クラス・カスタム要素の読み込み・モーダル開閉時のスクロール制御・Escape）
// Page-level side effects (body classes, custom element loading, modal scroll lock, Escape handling)
export function useMemoPageChrome({
  selectedMemo,
  closeMemoDetail,
  isShareModalOpen,
  setIsShareModalOpen,
  isCollectionPanelOpen,
  setIsCollectionPanelOpen,
  isExportModalOpen,
  setIsExportModalOpen,
}: UseMemoPageChromeParams) {
  // ページマウント時にカスタム要素の読み込みやボディのクラス設定を行う副作用
  // Effect to add body class and import custom elements on mount
  useEffect(() => {
    document.body.classList.add("memo-page");
    const importCustomElements = async () => {
      await Promise.all([import("../../scripts/components/popup_menu"), import("../../scripts/components/user_icon")]);
    };
    void importCustomElements();
    return () => {
      document.body.classList.remove("memo-page");
      document.body.classList.remove("modal-open");
    };
  }, []);

  // モーダル開閉時にbody要素のスクロールを制御するクラスを切り替える副作用
  // Effect to toggle a body class controlling scroll when modals open/close
  useEffect(() => {
    const open = Boolean(selectedMemo) || isShareModalOpen || isCollectionPanelOpen || isExportModalOpen;
    document.body.classList.toggle("modal-open", open);
    return () => { document.body.classList.remove("modal-open"); };
  }, [isShareModalOpen, selectedMemo, isCollectionPanelOpen, isExportModalOpen]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (isExportModalOpen) { setIsExportModalOpen(false); return; }
      if (isCollectionPanelOpen) { setIsCollectionPanelOpen(false); return; }
      if (isShareModalOpen) { setIsShareModalOpen(false); return; }
      if (selectedMemo) void closeMemoDetail();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); };
  }, [closeMemoDetail, isShareModalOpen, selectedMemo, isCollectionPanelOpen, isExportModalOpen, setIsCollectionPanelOpen, setIsExportModalOpen, setIsShareModalOpen]);
}
