import { useState } from "react";

import type { MemoView } from "../../lib/memo/types";

// メモ画面のレイアウト系 UI 状態（表示切替・グリッド/リスト・フィルタ開閉・サイドバー折りたたみ）
// Layout-level UI state for the memo page (view switch, grid/list, filter section, sidebar collapse)
export function useMemoPageLayout() {
  // Notebook 画面内の表示切替。"memos" は従来のメモ、"context" はマイコンテキスト金庫。
  // View switch inside the notebook: "memos" is the classic memo list, "context" is the vault.
  const [activeView, setActiveView] = useState<MemoView>("memos");

  // Keep-style board state
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");

  // Toolbar search/filter section (collapsible on mobile)
  const [isFiltersOpen, setIsFiltersOpen] = useState(false);

  // Collections sidebar
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

  return {
    activeView,
    setActiveView,
    viewMode,
    setViewMode,
    isFiltersOpen,
    setIsFiltersOpen,
    isSidebarCollapsed,
    setIsSidebarCollapsed,
  };
}
