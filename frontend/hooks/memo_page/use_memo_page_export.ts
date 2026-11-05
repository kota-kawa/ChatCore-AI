// メモのエクスポート（形式・対象範囲・対象メモの選択・ダウンロード開始）を扱うモーダル用のフック。
// Hook for the memo export modal: format, scope, memo selection, and starting the download.
import { useCallback, useEffect, useState } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { buildMemoExportUrl } from "../../lib/memo/api";
import type { FlashState, MemoExportFormat, MemoExportScope, MemoSummary } from "../../lib/memo/types";

type UseMemoPageExportParams = {
  memos: MemoSummary[];
  showFlash: (type: FlashState["type"], text: string) => void;
};

// エクスポートモーダル（形式・対象範囲・選択・ダウンロード開始）
// Export modal (format, scope, selection, download kick-off)
export function useMemoPageExport({ memos, showFlash }: UseMemoPageExportParams) {
  const { t } = useTranslation();

  // エクスポートモーダルの状態。
  // Export modal
  const [isExportModalOpen, setIsExportModalOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState<MemoExportFormat>("markdown");
  const [exportScope, setExportScope] = useState<MemoExportScope>("all");
  const [exportSelectedIds, setExportSelectedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!isExportModalOpen) return;
    setExportSelectedIds((prev) => {
      const memoIdSet = new Set(memos.map((m) => String(m.id)));
      const next = new Set([...prev].filter((id) => memoIdSet.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [isExportModalOpen, memos]);

  const toggleExportMemo = useCallback((memoId: string) => {
    setExportSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(memoId)) next.delete(memoId);
      else next.add(memoId);
      return next;
    });
    setExportScope("selected");
  }, []);

  const selectAllExportMemos = useCallback(() => {
    setExportSelectedIds(new Set(memos.map((memo) => String(memo.id))));
    setExportScope("selected");
  }, [memos]);

  const clearExportSelection = useCallback(() => {
    setExportSelectedIds(new Set());
  }, []);

  // 選択した形式（markdown / csv / json）でメモをエクスポートするハンドラー。ダウンロード用のリンクを作ってクリックする
  // Handler to export memos in the chosen format (markdown / csv / json) by creating and clicking a download link
  const handleExport = useCallback(() => {
    if (exportScope === "selected" && exportSelectedIds.size === 0) {
      showFlash("error", t("memo.exportSelectionRequired"));
      return;
    }
    const ids = exportScope === "selected" ? Array.from(exportSelectedIds) : [];
    const url = buildMemoExportUrl(exportFormat, ids);
    const a = document.createElement("a");
    a.href = url;
    a.download = `memos.${exportFormat === "json" ? "json" : exportFormat === "csv" ? "csv" : "md"}`;
    a.click();
    setIsExportModalOpen(false);
    showFlash("success", t("memo.exportStarted"));
  }, [exportFormat, exportScope, exportSelectedIds, showFlash]);

  const exportSelectedCount = exportSelectedIds.size;
  const visibleExportIds = memos.map((memo) => String(memo.id));
  const allVisibleExportSelected = visibleExportIds.length > 0 && visibleExportIds.every((id) => exportSelectedIds.has(id));
  const canDownloadExport = exportScope === "all" || exportSelectedCount > 0;

  return {
    isExportModalOpen,
    setIsExportModalOpen,
    exportFormat,
    setExportFormat,
    exportScope,
    setExportScope,
    exportSelectedIds,
    exportSelectedCount,
    allVisibleExportSelected,
    canDownloadExport,
    toggleExportMemo,
    selectAllExportMemos,
    clearExportSelection,
    handleExport,
  };
}
