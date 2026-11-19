// メモ画面のレイアウト系 UI 状態（表示切替、グリッド/リスト、フィルタ開閉、サイドバー折りたたみ）を保持するフック。
// Hook holding the memo page layout UI state: view switch, grid/list mode, filter section, and sidebar collapse.
import { useEffect, useState } from "react";
import { useRouter } from "next/router";

import type { MemoView } from "../../lib/memo/types";

// メモ画面のレイアウト系 UI 状態（表示切替・グリッド/リスト・フィルタ開閉・サイドバー折りたたみ）
// Layout-level UI state for the memo page (view switch, grid/list, filter section, sidebar collapse)
export function useMemoPageLayout() {
  // Notebook 画面内の表示切替。"memos" は従来のメモ、"context" は記憶（パーソナル・コンテキスト）。
  // View switch inside the notebook: "memos" is the classic memo list, "context" is Memory (the personal context).
  const [activeView, setActiveView] = useState<MemoView>("memos");

  // チャットの「記憶しました」通知のリンク（/memo?view=context）で、記憶の画面を直接開く。
  // 初回描画をサーバーと一致させるため、ルーターが使えるようになってから切り替える。
  // The chat's "remembered" notice links to /memo?view=context to open the memory view directly.
  // The switch happens once the router is ready so the first render matches the server.
  const router = useRouter();
  const requestedView = router.isReady ? router.query.view : undefined;
  useEffect(() => {
    if (requestedView === "context") setActiveView("context");
  }, [requestedView]);

  // Keep 風ボードの表示状態（グリッド/リスト）。
  // Keep-style board state
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");

  // ツールバーの検索・絞り込み欄（スマホでは開閉できる）。
  // Toolbar search/filter section (collapsible on mobile)
  const [isFiltersOpen, setIsFiltersOpen] = useState(false);

  // コレクションのサイドバー。
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
