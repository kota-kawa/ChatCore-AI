import { type Dispatch, type SetStateAction } from "react";

import type { Collection } from "../../lib/memo/types";
import { MemoSelect } from "./MemoSelect";

type MemoToolbarProps = {
  activeCollection: Collection | null | undefined;
  activeCollectionId: number | null;
  archiveScope: string;
  sortMode: string;
  collections: Collection[];
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
  isFiltersOpen: boolean;
  setIsFiltersOpen: Dispatch<SetStateAction<boolean>>;
  setIsCollectionPanelOpen: (value: boolean) => void;
};

// ── Toolbar ──
export function MemoToolbar({
  activeCollection,
  activeCollectionId,
  archiveScope,
  sortMode,
  collections,
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
  isFiltersOpen,
  setIsFiltersOpen,
  setIsCollectionPanelOpen,
}: MemoToolbarProps) {
  return (
            <header className={`memo-toolbar memo-card${isFiltersOpen ? " is-filters-open" : ""}`}>
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
                  <button
                    type="button"
                    className={`memo-toolbar__icon-btn memo-toolbar__filter-toggle${hasActiveFilters ? " has-active-filters" : ""}`}
                    onClick={() => setIsFiltersOpen((current) => !current)}
                    aria-label="表示・整理メニュー"
                    aria-expanded={isFiltersOpen}
                    aria-controls="memo-mobile-controls"
                    data-tooltip="表示・整理"
                    data-tooltip-placement="bottom"
                  >
                    <i className="bi bi-sliders" aria-hidden="true"></i>
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
              <section id="memo-mobile-controls" className="memo-toolbar__mobile-controls" aria-label="メモの表示・整理">
                <div className="memo-mobile-controls__scope" role="group" aria-label="表示範囲">
                  <button
                    type="button"
                    className={`memo-filter-chip${archiveScope === "active" && activeCollectionId === null ? " is-active" : ""}`}
                    onClick={() => { setActiveCollectionId(null); setArchiveScope("active"); }}
                  >
                    <i className="bi bi-lightning-charge" aria-hidden="true"></i>
                    すべてのメモ
                  </button>
                  <button
                    type="button"
                    className={`memo-filter-chip${archiveScope === "archived" ? " is-active" : ""}`}
                    onClick={() => { setActiveCollectionId(null); setArchiveScope("archived"); }}
                  >
                    <i className="bi bi-archive" aria-hidden="true"></i>
                    アーカイブ
                  </button>
                </div>
                <div className="memo-mobile-controls__field">
                  <label className="memo-mobile-controls__label">並び順</label>
                  <MemoSelect
                    ariaLabel="並び順"
                    value={sortMode}
                    onChange={setSortMode}
                    options={[
                      { value: "manual", label: "手動順" },
                      { value: "recent", label: "新しい順" },
                      { value: "updated", label: "更新順" },
                      { value: "oldest", label: "古い順" },
                      { value: "title", label: "タイトル順" },
                      { value: "semantic", label: "AI類似検索" },
                    ]}
                  />
                </div>
                <div className="memo-mobile-controls__field">
                  <label className="memo-mobile-controls__label">コレクション</label>
                  <MemoSelect
                    ariaLabel="コレクション"
                    className="memo-select--collection-filter"
                    value={String(activeCollectionId ?? "")}
                    onChange={(value) => setActiveCollectionId(value === "" ? null : Number(value))}
                    options={[
                      { value: "", label: "すべてのコレクション" },
                      ...collections.map((collection) => ({ value: String(collection.id), label: collection.name })),
                    ]}
                  />
                </div>
                <button
                  type="button"
                  className="memo-mobile-controls__manage"
                  onClick={() => setIsCollectionPanelOpen(true)}
                >
                  <i className="bi bi-folder2-open" aria-hidden="true"></i>
                  コレクションを管理
                </button>
              </section>
            </header>
  );
}
