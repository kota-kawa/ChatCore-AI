import { SeoHead } from "../../SeoHead";
import { useTranslation } from "../../../contexts/locale_context";

import "../../../scripts/core/csrf";

import { MemoBulkBar } from "../MemoBulkBar";
import { MemoCollectionModal } from "../MemoCollectionModal";
import { MemoComposer } from "../MemoComposer";
import { MemoCrawlSummary } from "../MemoCrawlSummary";
import { MemoDetailModal } from "../MemoDetailModal";
import { MemoExportModal } from "../MemoExportModal";
import { MemoHistoryPanel } from "../MemoHistoryPanel";
import { MemoShareModal } from "../MemoShareModal";
import { MemoSidebar } from "../MemoSidebar";
import { MemoToolbar } from "../MemoToolbar";
import { MyContextPanel } from "../MyContextPanel";
import { MemoViewSwitcher } from "../MemoViewSwitcher";
import { MemoPageContextProvider } from "../../../contexts/memo_page/memo_page_context";
import { useMemoPageController } from "../../../hooks/memo_page/use_memo_page_controller";
import { memoPageDescription, memoStructuredData } from "../../../lib/memo/constants";

// MemoCrawlSummary はメモ画面の公開コンテンツとして別モジュールへ切り出した。
// 既存のテストとの互換性のためにこのモジュールから再エクスポートする。
// MemoCrawlSummary was extracted into its own module; re-export it here so that
// existing imports (and tests) referencing this page keep working.
export { MemoCrawlSummary };

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

// メモ機能のメインページコンポーネント。状態と操作は hooks/memo_page/ の機能別 hook が持ち、
// 子コンポーネントは MemoPageContextProvider 経由で必要なスライスだけを読む。
// ここで直接使うのはページ骨格の描画に必要な数個の値だけ。
// Main page component for the memo feature. State and actions live in the feature hooks
// under hooks/memo_page/; children read the slices they need through MemoPageContextProvider.
// Only the handful of values needed for the page skeleton are read here directly.
export default function MemoPage() {
  const { locale, t } = useTranslation();
  const controller = useMemoPageController();
  const {
    isLoggedIn,
    authUiReady,
    isSidebarCollapsed,
    activeView,
    setActiveView,
    flashState,
    isBulkMode,
    viewMode,
  } = controller;

  return (
    <>
      <SeoHead
        title={t("memo.title")}
        description={locale === "en" ? "Save, organize, search, and share your notes and useful AI responses." : memoPageDescription}
        canonicalPath="/memo"
        structuredData={memoStructuredData}
      />

      <MemoPageContextProvider controller={controller}>
        <div className="memo-page-shell cc-page-rise">
          {/* 検索エンジン・支援技術向けの説明的なページ見出し（視覚的には非表示） */}
          {/* Descriptive page heading for search engines and assistive tech (visually hidden) */}
          <h1 className="sr-only">{locale === "en" ? "Chat Core Memos — save, organize, and share useful knowledge" : "Chat Core メモ ― AIの回答や作業メモを保存・整理・共有"}</h1>
          <action-menu></action-menu>

          <div
            id="auth-buttons"
            style={{
              display: authUiReady && !isLoggedIn ? "" : "none",
              position: "fixed",
              top: 10,
              right: 10,
              zIndex: "var(--z-floating-controls, 65)",
            }}
          >
            <button type="button" id="login-btn" className="auth-btn" onClick={() => { window.location.href = "/login"; }}>
              <i className="bi bi-person-circle"></i>
              <span>{locale === "en" ? "Log in / Sign up" : "ログイン / 登録"}</span>
            </button>
          </div>

          <user-icon id="userIcon" style={authUiReady && isLoggedIn ? undefined : { display: "none" }}></user-icon>

          <div className={`memo-layout${isSidebarCollapsed ? " is-sidebar-collapsed" : ""}`}>
            <MemoSidebar />

            <div className="memo-container">
              <MemoViewSwitcher activeView={activeView} setActiveView={setActiveView} />
              {activeView === "context" ? (
              <MyContextPanel isLoggedIn={isLoggedIn} />
              ) : (
              <>
              {/* 未ログイン時のみ表示する機能紹介テキスト（クロール可能な公開コンテンツを確保する） */}
              {/* Short feature intro shown only when logged out (provides crawlable public content) */}
              {!isLoggedIn && (
                <p className="memo-guest-intro">{t("memo.guestIntro")}</p>
              )}
              {/* ── Toolbar ── */}
              <MemoToolbar />

            {flashState && (
              <div className={`memo-flash memo-flash--${flashState.type}`} role="alert">
                {flashState.text}
              </div>
            )}

            <MemoCrawlSummary />

            {/* Bulk action bar */}
            {isBulkMode && (
              <MemoBulkBar />
            )}

            {/* ── Quick capture ── */}
            <MemoComposer />

            <div className={`memo-board memo-board--${viewMode}`}>
              {/* ── Memo list ── */}
              <MemoHistoryPanel />
            </div>
              </>
              )}
            </div>
          </div>

          {/* ── Memo detail modal ── */}
          <MemoDetailModal />

          {/* ── Share modal ── */}
          <MemoShareModal />

          {/* ── Collection management panel ── */}
          <MemoCollectionModal />

          {/* ── Export modal ── */}
          <MemoExportModal />
        </div>
      </MemoPageContextProvider>
    </>
  );
}
