import { useEffect } from "react";

import type { MemoDetail, MemoView } from "../../lib/memo/types";
import { useMemoMobileLayout, useMemoViewport } from "./use_memo_viewport";

type UseMemoPageChromeParams = {
  selectedMemo: MemoDetail | null;
  isShareModalOpen: boolean;
  isCollectionPanelOpen: boolean;
  isExportModalOpen: boolean;
  composeIsExpanded: boolean;
  activeView: MemoView;
};

// ページ全体の副作用（body クラス・カスタム要素の読み込み・モーダル開閉時のスクロール制御）
// Page-level side effects (body classes, custom element loading, modal scroll lock)
export function useMemoPageChrome({
  selectedMemo,
  isShareModalOpen,
  isCollectionPanelOpen,
  isExportModalOpen,
  composeIsExpanded,
  activeView,
}: UseMemoPageChromeParams) {
  const isMobile = useMemoMobileLayout();
  const composingOnMobile = composeIsExpanded && isMobile;
  const viewportStyle = useMemoViewport(composingOnMobile);
  const viewportTop = (viewportStyle as Record<string, string> | undefined)?.["--memo-viewport-top"] ?? "0px";

  useEffect(() => {
    const menu = document.querySelector<HTMLElement>("action-menu");
    if (!menu) return;
    const agentButton = document.querySelector<HTMLElement>(".global-ai-agent-button");
    const syncMenu = () => {
      const composing = document.body.classList.contains("memo-compose-open");
      const toolbar = document.querySelector(".memo-toolbar");
      menu.toggleAttribute("data-memo-composing", composing);
      menu.toggleAttribute("data-memo-page", isMobile && activeView === "memos");
      agentButton?.toggleAttribute("data-memo-page", isMobile && activeView === "memos");
      const top = composing ? `calc(${viewportTop} + 8px)` : `${(toolbar?.getBoundingClientRect().top ?? 0) + window.scrollY + 8}px`;
      menu.style.setProperty("--memo-menu-top", top);
      agentButton?.style.setProperty("--memo-menu-top", top);
    };
    syncMenu();
    const observer = new MutationObserver(syncMenu);
    observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    const container = document.querySelector(".memo-container");
    const contentObserver = new MutationObserver(syncMenu);
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(syncMenu);
    if (container) {
      contentObserver.observe(container, { childList: true, subtree: true });
      resizeObserver?.observe(container);
    }
    window.addEventListener("resize", syncMenu);
    window.addEventListener("orientationchange", syncMenu);
    return () => {
      observer.disconnect();
      contentObserver.disconnect();
      resizeObserver?.disconnect();
      window.removeEventListener("resize", syncMenu);
      window.removeEventListener("orientationchange", syncMenu);
      menu.removeAttribute("data-memo-composing");
      menu.removeAttribute("data-memo-page");
      menu.style.removeProperty("--memo-menu-top");
      agentButton?.removeAttribute("data-memo-page");
      agentButton?.style.removeProperty("--memo-menu-top");
    };
  }, [activeView, isMobile, viewportTop]);

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
