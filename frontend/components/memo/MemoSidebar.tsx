import { type Dispatch, type SetStateAction } from "react";

import type { Collection } from "../../lib/memo/types";
import { MemoSelect } from "./MemoSelect";

type MemoSidebarProps = {
  isSidebarCollapsed: boolean;
  setIsSidebarCollapsed: Dispatch<SetStateAction<boolean>>;
  activeCollectionId: number | null;
  setActiveCollectionId: Dispatch<SetStateAction<number | null>>;
  archiveScope: string;
  setArchiveScope: Dispatch<SetStateAction<string>>;
  sortMode: string;
  setSortMode: Dispatch<SetStateAction<string>>;
  collections: Collection[];
  setIsCollectionPanelOpen: (value: boolean) => void;
};

export function MemoSidebar({
  isSidebarCollapsed,
  setIsSidebarCollapsed,
  activeCollectionId,
  setActiveCollectionId,
  archiveScope,
  setArchiveScope,
  sortMode,
  setSortMode,
  collections,
  setIsCollectionPanelOpen,
}: MemoSidebarProps) {
  return (
          <aside className="memo-sidebar">
            <header className="memo-sidebar-header">
              <div className="memo-sidebar-brand">
                <span className="memo-sidebar-brand-icon" aria-hidden="true">
                  <i className="bi bi-journal-bookmark-fill"></i>
                </span>
                <span className="memo-sidebar-title">Notebook</span>
              </div>
              <button
                type="button"
                className="memo-sidebar-toggle"
                onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
                aria-label={isSidebarCollapsed ? "サイドバーを展開" : "サイドバーを折りたたむ"}
                data-tooltip={isSidebarCollapsed ? "サイドバーを展開" : "サイドバーを折りたたむ"}
                data-tooltip-placement="right"
              >
                <i className={`bi ${isSidebarCollapsed ? "bi-layout-sidebar" : "bi-layout-sidebar-inset"}`} aria-hidden="true"></i>
              </button>
            </header>

            <div className="memo-sidebar-inner">
              <nav className="memo-sidebar-nav">
                <button
                  type="button"
                  className={`memo-sidebar-nav__item${activeCollectionId === null && archiveScope === "active" ? " is-active" : ""}`}
                  onClick={() => { setActiveCollectionId(null); setArchiveScope("active"); }}
                >
                  <i className="bi bi-lightning-charge" aria-hidden="true"></i>
                  <span>すべてのメモ</span>
                </button>
                <button
                  type="button"
                  className={`memo-sidebar-nav__item${archiveScope === "archived" ? " is-active" : ""}`}
                  onClick={() => { setActiveCollectionId(null); setArchiveScope("archived"); }}
                >
                  <i className="bi bi-archive" aria-hidden="true"></i>
                  <span>アーカイブ</span>
                </button>
              </nav>

              <div className="memo-sidebar-divider" role="separator"></div>

              <section className="memo-sidebar-section">
                <h3 className="memo-sidebar-section__title">並び順</h3>
                <div className="memo-sidebar-sort">
                  <MemoSelect
                    value={sortMode}
                    onChange={(v) => setSortMode(v)}
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
              </section>

              <div className="memo-sidebar-divider" role="separator"></div>

              <section className="memo-sidebar-section">
                <h3 className="memo-sidebar-section__title">コレクション</h3>
                <div className="memo-sidebar-collection-list">
                  {collections.map((col) => (
                    <button
                      key={col.id}
                      type="button"
                      className={`memo-sidebar-collection-item${activeCollectionId === col.id ? " is-active" : ""}`}
                      onClick={() => setActiveCollectionId(col.id)}
                    >
                      <span className="memo-sidebar-collection-dot" style={{ background: col.color }}></span>
                      <span className="memo-sidebar-collection-name">{col.name}</span>
                      <span className="memo-sidebar-collection-count">{col.memo_count}</span>
                    </button>
                  ))}
                  {collections.length === 0 && (
                    <p className="memo-sidebar-collection-empty">コレクションなし</p>
                  )}
                </div>
                <button
                  type="button"
                  className="memo-sidebar-manage-btn"
                  onClick={() => setIsCollectionPanelOpen(true)}
                >
                  <i className="bi bi-plus-circle" aria-hidden="true"></i>
                  <span>コレクションを管理</span>
                </button>
              </section>
            </div>
          </aside>
  );
}
