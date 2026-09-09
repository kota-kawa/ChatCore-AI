import { useEffect } from "react";

import type { MemoDetail } from "../../lib/memo/types";

type UseMemoPageChromeParams = {
  selectedMemo: MemoDetail | null;
  isShareModalOpen: boolean;
  isCollectionPanelOpen: boolean;
  isExportModalOpen: boolean;
};

// ページ全体の副作用（body クラス・カスタム要素の読み込み・モーダル開閉時のスクロール制御）
// Page-level side effects (body classes, custom element loading, modal scroll lock)
export function useMemoPageChrome({
  selectedMemo,
  isShareModalOpen,
  isCollectionPanelOpen,
  isExportModalOpen,
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

  // Escape で閉じる処理は各モーダルの ModalShell（フォーカストラップ）が担うため、ここでは扱わない。
  // Escape-to-close is handled by each modal's ModalShell (focus trap), so it is not duplicated here.
}
