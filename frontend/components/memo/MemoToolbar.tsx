import type { Collection } from "../../lib/memo/types";
import { MemoSelect } from "./MemoSelect";
import { useTranslation } from "../../contexts/locale_context";
import {
  useMemoPageBoardContext,
  useMemoPageListContext,
  useMemoPageModalsContext,
  useMemoPageUiContext,
} from "../../contexts/memo_page/memo_page_context";

// ── Toolbar ──
export function MemoToolbar() {
  const { viewMode, setViewMode, isFiltersOpen, setIsFiltersOpen } = useMemoPageUiContext();
  const {
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
  } = useMemoPageListContext();
  const { isBulkMode, exitBulkMode, setIsBulkMode } = useMemoPageBoardContext();
  const { setIsExportModalOpen, setIsCollectionPanelOpen } = useMemoPageModalsContext();
  const { locale, t } = useTranslation();
  const english = locale === "en";
  const sortOptions = english
    ? [{ value: "manual", label: "Manual" }, { value: "recent", label: "Newest" }, { value: "updated", label: "Recently updated" }, { value: "oldest", label: "Oldest" }, { value: "title", label: "Title" }, { value: "semantic", label: "AI similarity" }]
    : [{ value: "manual", label: "手動順" }, { value: "recent", label: "新しい順" }, { value: "updated", label: "更新順" }, { value: "oldest", label: "古い順" }, { value: "title", label: "タイトル順" }, { value: "semantic", label: "AI類似検索" }];
  return (
            <header className={`memo-toolbar memo-card${isFiltersOpen ? " is-filters-open" : ""}`}>
              <div className="memo-toolbar__top-row">
                <div className="memo-toolbar__brand">
                  <div className="memo-toolbar__title">
                    <h2>{activeCollection ? activeCollection.name : archiveScope === "archived" ? (english ? "Archive" : "アーカイブ") : t("memo.heading")}</h2>
                    <span className="memo-toolbar__count">
                      {english ? `${totalMemoCount} items` : `${totalMemoCount}件`}
                    </span>
                  </div>
                </div>
                <div className="memo-toolbar__actions" role="toolbar" aria-label={english ? "Memo actions" : "メモ操作"}>
                  <button
                    type="button"
                    className="memo-toolbar__icon-btn"
                    onClick={() => setViewMode((current) => (current === "grid" ? "list" : "grid"))}
                    aria-label={viewMode === "grid" ? (english ? "List view" : "リスト表示") : (english ? "Grid view" : "グリッド表示")}
                    data-tooltip={viewMode === "grid" ? (english ? "List view" : "リスト表示") : (english ? "Grid view" : "グリッド表示")}
                    data-tooltip-placement="bottom"
                  >
                    <i className={`bi ${viewMode === "grid" ? "bi-view-list" : "bi-grid-3x3-gap"}`} aria-hidden="true"></i>
                  </button>
                  <button
                    type="button"
                    className={`memo-toolbar__icon-btn${isBulkMode ? " is-active" : ""}`}
                    onClick={() => { if (isBulkMode) exitBulkMode(); else setIsBulkMode(true); }}
                    aria-label={english ? "Bulk actions" : "一括操作"}
                    data-tooltip={english ? "Bulk actions" : "一括操作"}
                    data-tooltip-placement="bottom"
                  >
                    <i className={`bi ${isBulkMode ? "bi-check2-square" : "bi-ui-checks"}`} aria-hidden="true"></i>
                  </button>
                  <button
                    type="button"
                    className="memo-toolbar__icon-btn"
                    onClick={() => setIsExportModalOpen(true)}
                    aria-label={t("memo.export")}
                    data-tooltip={t("memo.export")}
                    data-tooltip-placement="bottom"
                  >
                    <i className="bi bi-download" aria-hidden="true"></i>
                  </button>
                  <button
                    type="button"
                    className={`memo-toolbar__icon-btn memo-toolbar__filter-toggle${hasActiveFilters ? " has-active-filters" : ""}`}
                    onClick={() => setIsFiltersOpen((current) => !current)}
                    aria-label={english ? "View and organize" : "表示・整理メニュー"}
                    aria-expanded={isFiltersOpen}
                    aria-controls="memo-mobile-controls"
                    data-tooltip={english ? "View and organize" : "表示・整理"}
                    data-tooltip-placement="bottom"
                  >
                    <i className="bi bi-sliders" aria-hidden="true"></i>
                  </button>
                </div>
              </div>
              <div className="memo-toolbar__search">
                <label htmlFor="memo-search" className="sr-only">{t("memo.search")}</label>
                <i className="bi bi-search" aria-hidden="true"></i>
                <input
                  id="memo-search"
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t("memo.search")}
                />
                {hasActiveFilters && (
                  <button
                    type="button"
                    className="memo-toolbar__search-clear"
                    onClick={() => { setQuery(""); setArchiveScope("active"); setSortMode("manual"); setActiveCollectionId(null); }}
                    aria-label={english ? "Clear filters" : "クリア"}
                  >
                    <i className="bi bi-x-lg" aria-hidden="true"></i>
                  </button>
                )}
              </div>
              <section id="memo-mobile-controls" className="memo-toolbar__mobile-controls" aria-label={english ? "View and organize memos" : "メモの表示・整理"}>
                <div className="memo-mobile-controls__scope" role="group" aria-label={english ? "Scope" : "表示範囲"}>
                  <button
                    type="button"
                    className={`memo-filter-chip${archiveScope === "active" && activeCollectionId === null ? " is-active" : ""}`}
                    onClick={() => { setActiveCollectionId(null); setArchiveScope("active"); }}
                  >
                    <i className="bi bi-lightning-charge" aria-hidden="true"></i>
                    {english ? "All memos" : "すべてのメモ"}
                  </button>
                  <button
                    type="button"
                    className={`memo-filter-chip${archiveScope === "archived" ? " is-active" : ""}`}
                    onClick={() => { setActiveCollectionId(null); setArchiveScope("archived"); }}
                  >
                    <i className="bi bi-archive" aria-hidden="true"></i>
                    {english ? "Archive" : "アーカイブ"}
                  </button>
                </div>
                <div className="memo-mobile-controls__field">
                  <label className="memo-mobile-controls__label">{english ? "Sort" : "並び順"}</label>
                  <MemoSelect
                    ariaLabel={english ? "Sort" : "並び順"}
                    value={sortMode}
                    onChange={setSortMode}
                    options={sortOptions}
                  />
                </div>
                <div className="memo-mobile-controls__field">
                  <label className="memo-mobile-controls__label">{english ? "Collection" : "コレクション"}</label>
                  <MemoSelect
                    ariaLabel={english ? "Collection" : "コレクション"}
                    className="memo-select--collection-filter"
                    value={String(activeCollectionId ?? "")}
                    onChange={(value) => setActiveCollectionId(value === "" ? null : Number(value))}
                    options={[
                      { value: "", label: english ? "All collections" : "すべてのコレクション" },
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
                  {english ? "Manage collections" : "コレクションを管理"}
                </button>
              </section>
            </header>
  );
}
