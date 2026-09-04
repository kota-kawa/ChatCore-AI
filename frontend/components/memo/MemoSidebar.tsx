import { MemoSelect } from "./MemoSelect";
import { useTranslation } from "../../contexts/locale_context";
import {
  useMemoPageListContext,
  useMemoPageModalsContext,
  useMemoPageUiContext,
} from "../../contexts/memo_page/memo_page_context";

export function MemoSidebar() {
  const { isSidebarCollapsed, setIsSidebarCollapsed, activeView, setActiveView } = useMemoPageUiContext();
  const {
    activeCollectionId,
    setActiveCollectionId,
    archiveScope,
    setArchiveScope,
    sortMode,
    setSortMode,
    collections,
  } = useMemoPageListContext();
  const { setIsCollectionPanelOpen } = useMemoPageModalsContext();
  const { t } = useTranslation();
  const isMemosView = activeView === "memos";
  return (
          <aside className="memo-sidebar">
            <header className="memo-sidebar-header">
              <div className="memo-sidebar-brand">
                <span className="memo-sidebar-brand-icon" aria-hidden="true">
                  <img src="/static/chatcore-memo.png" alt="" />
                </span>
                <span className="memo-sidebar-title">ChatCore Memo</span>
              </div>
              <button
                type="button"
                className="memo-sidebar-toggle"
                onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
                aria-label={isSidebarCollapsed ? t("memo.expandSidebar") : t("memo.collapseSidebar")}
                data-tooltip={isSidebarCollapsed ? t("memo.expandSidebar") : t("memo.collapseSidebar")}
                data-tooltip-placement="right"
              >
                <i className={`bi ${isSidebarCollapsed ? "bi-layout-sidebar" : "bi-layout-sidebar-inset"}`} aria-hidden="true"></i>
              </button>
            </header>

            <div className="memo-sidebar-inner">
              <nav className="memo-sidebar-nav">
                <button
                  type="button"
                  className={`memo-sidebar-nav__item${isMemosView && activeCollectionId === null && archiveScope === "active" ? " is-active" : ""}`}
                  onClick={() => { setActiveView("memos"); setActiveCollectionId(null); setArchiveScope("active"); }}
                >
                  <i className="bi bi-lightning-charge" aria-hidden="true"></i>
                  <span>{t("memo.allMemos")}</span>
                </button>
                <button
                  type="button"
                  className={`memo-sidebar-nav__item${activeView === "context" ? " is-active" : ""}`}
                  onClick={() => setActiveView("context")}
                >
                  <i className="bi bi-safe" aria-hidden="true"></i>
                  <span>{t("memo.myContext")}</span>
                </button>
              </nav>

              {isMemosView && (
                <>
                  <div className="memo-sidebar-divider" role="separator"></div>

                  <section className="memo-sidebar-section">
                    <h3 className="memo-sidebar-section__title">{t("memo.sort")}</h3>
                    <div className="memo-sidebar-sort">
                      <MemoSelect
                        value={sortMode}
                        onChange={(v) => setSortMode(v)}
                        options={[
                          { value: "manual", label: t("memo.sortManual") },
                          { value: "recent", label: t("memo.sortNewest") },
                          { value: "updated", label: t("memo.sortUpdated") },
                          { value: "oldest", label: t("memo.sortOldest") },
                          { value: "title", label: t("memo.sortTitle") },
                          { value: "semantic", label: t("memo.sortSemantic") },
                        ]}
                      />
                    </div>
                  </section>

                  <div className="memo-sidebar-divider" role="separator"></div>

                  <section className="memo-sidebar-section">
                    <h3 className="memo-sidebar-section__title">{t("memo.collections")}</h3>
                    <div className="memo-sidebar-collection-list">
                      <button
                        type="button"
                        className={`memo-sidebar-collection-item memo-sidebar-collection-item--system${archiveScope === "archived" ? " is-active" : ""}`}
                        onClick={() => { setActiveView("memos"); setActiveCollectionId(null); setArchiveScope("archived"); }}
                      >
                        <span className="memo-sidebar-collection-icon" aria-hidden="true">
                          <i className="bi bi-archive"></i>
                        </span>
                        <span className="memo-sidebar-collection-name">{t("memo.archive")}</span>
                      </button>
                      {collections.map((col) => (
                        <button
                          key={col.id}
                          type="button"
                          className={`memo-sidebar-collection-item${activeCollectionId === col.id ? " is-active" : ""}`}
                          onClick={() => { setActiveView("memos"); setActiveCollectionId(col.id); }}
                        >
                          <span className="memo-sidebar-collection-dot" style={{ background: col.color }}></span>
                          <span className="memo-sidebar-collection-name">{col.name}</span>
                          <span className="memo-sidebar-collection-count">{col.memo_count}</span>
                        </button>
                      ))}
                      {collections.length === 0 && (
                        <p className="memo-sidebar-collection-empty">{t("memo.noCollection")}</p>
                      )}
                    </div>
                    <button
                      type="button"
                      className="memo-sidebar-manage-btn"
                      onClick={() => setIsCollectionPanelOpen(true)}
                    >
                      <i className="bi bi-plus-circle" aria-hidden="true"></i>
                      <span>{t("memo.manageCollections")}</span>
                    </button>
                  </section>
                </>
              )}
            </div>
          </aside>
  );
}
