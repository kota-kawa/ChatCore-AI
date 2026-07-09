import { type Dispatch, type SetStateAction } from "react";

import type { Collection } from "../../lib/memo/types";

type MemoToolbarProps = {
  activeCollection: Collection | null | undefined;
  archiveScope: string;
  totalMemoCount: number;
  query: string;
  setQuery: Dispatch<SetStateAction<string>>;
  hasActiveFilters: boolean;
  setArchiveScope: Dispatch<SetStateAction<string>>;
  setSortMode: Dispatch<SetStateAction<string>>;
  setActiveCollectionId: Dispatch<SetStateAction<number | null>>;
  viewMode: "grid" | "list";
  setViewMode: Dispatch<SetStateAction<"grid" | "list">>;
  isBulkMode: boolean;
  exitBulkMode: () => void;
  setIsBulkMode: Dispatch<SetStateAction<boolean>>;
  setIsExportModalOpen: (value: boolean) => void;
};

// ── Toolbar ──
export function MemoToolbar({
  activeCollection,
  archiveScope,
  totalMemoCount,
  query,
  setQuery,
  hasActiveFilters,
  setArchiveScope,
  setSortMode,
  setActiveCollectionId,
  viewMode,
  setViewMode,
  isBulkMode,
  exitBulkMode,
  setIsBulkMode,
  setIsExportModalOpen,
}: MemoToolbarProps) {
  return (
            <header className="memo-toolbar memo-card">
              <div className="memo-toolbar__top-row">
                <div className="memo-toolbar__brand">
                  <div className="memo-toolbar__title">
                    <h2>{activeCollection ? activeCollection.name : archiveScope === "archived" ? "アーカイブ" : "メモ"}</h2>
                    <span className="memo-toolbar__count">
                      {totalMemoCount}件
                    </span>
                  </div>
                </div>
                <div className="memo-toolbar__actions" role="toolbar" aria-label="メモ操作">
                  <button
                    type="button"
                    className="memo-toolbar__icon-btn"
                    onClick={() => setViewMode((current) => (current === "grid" ? "list" : "grid"))}
                    aria-label={viewMode === "grid" ? "リスト表示" : "グリッド表示"}
                    data-tooltip={viewMode === "grid" ? "リスト表示" : "グリッド表示"}
                    data-tooltip-placement="bottom"
                  >
                    <i className={`bi ${viewMode === "grid" ? "bi-view-list" : "bi-grid-3x3-gap"}`} aria-hidden="true"></i>
                  </button>
                  <button
                    type="button"
                    className={`memo-toolbar__icon-btn${isBulkMode ? " is-active" : ""}`}
                    onClick={() => { if (isBulkMode) exitBulkMode(); else setIsBulkMode(true); }}
                    aria-label="一括操作"
                    data-tooltip="一括操作"
                    data-tooltip-placement="bottom"
                  >
                    <i className={`bi ${isBulkMode ? "bi-check2-square" : "bi-ui-checks"}`} aria-hidden="true"></i>
                  </button>
                  <button
                    type="button"
                    className="memo-toolbar__icon-btn"
                    onClick={() => setIsExportModalOpen(true)}
                    aria-label="エクスポート"
                    data-tooltip="エクスポート"
                    data-tooltip-placement="bottom"
                  >
                    <i className="bi bi-download" aria-hidden="true"></i>
                  </button>
                </div>
              </div>
              <div className="memo-toolbar__search">
                <label htmlFor="memo-search" className="sr-only">メモを検索</label>
                <i className="bi bi-search" aria-hidden="true"></i>
                <input
                  id="memo-search"
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="検索..."
                />
                {hasActiveFilters && (
                  <button
                    type="button"
                    className="memo-toolbar__search-clear"
                    onClick={() => { setQuery(""); setArchiveScope("active"); setSortMode("manual"); setActiveCollectionId(null); }}
                    aria-label="クリア"
                  >
                    <i className="bi bi-x-lg" aria-hidden="true"></i>
                  </button>
                )}
              </div>
            </header>
  );
}
