// メモ画面（/memo）のページ本体。サイドバー・ツールバー・作成欄・一覧と各モーダルを並べ、状態は MemoPageControllerProvider の context から受け取る。pages/memo.tsx から使われる。
// Page body of the memo screen (/memo): arranges the sidebar, toolbar, composer, list, and modals, with state coming from the MemoPageControllerProvider context. Used by pages/memo.tsx.
import { SeoHead } from "../../SeoHead";
import { useTranslation } from "../../../contexts/locale_context";

import "../../../scripts/core/csrf";

import { MemoBulkBar } from "../MemoBulkBar";
import { MemoCollectionModal } from "../MemoCollectionModal";
import { MemoComposer } from "../MemoComposer";
import { MemoCrawlSummary } from "../MemoCrawlSummary";
import { MemoDetailModal } from "../MemoDetailModal";
import { MemoExportModal } from "../MemoExportModal";
import { MemoFlashToast } from "../MemoFlashToast";
import { MemoHistoryPanel } from "../MemoHistoryPanel";
import { MemoNewFab } from "../MemoNewFab";
import { MemoShareModal } from "../MemoShareModal";
import { MemoSidebar } from "../MemoSidebar";
import { MemoToolbar } from "../MemoToolbar";
import { MyContextPanel } from "../MyContextPanel";
import { MemoViewSwitcher } from "../MemoViewSwitcher";
import {
  MemoPageControllerProvider,
  useMemoPageBoardContext,
  useMemoPageFlashContext,
  useMemoPageListContext,
  useMemoPageUiContext,
} from "../../../contexts/memo_page/memo_page_context";
import { memoPageDescription, memoStructuredData } from "../../../lib/memo/constants";

// ---------------------------------------------------------------------------
// メインページ
// Main page
// ---------------------------------------------------------------------------

// controller の更新とページ骨格の描画を別コンポーネントに分け、入力ごとに一覧全体を
// 再評価しないようにする。children は controller provider の再描画間で同じ要素を保つ。
// Keep controller updates separate from the page shell so composer input does not re-evaluate
// the whole memo list. The children element stays stable across controller updates.
export default function MemoPage() {
  const { locale, t } = useTranslation();

  return (
    <>
      <SeoHead
        title={t("memo.title")}
        description={locale === "en" ? "Save, organize, search, and share your notes and useful AI responses." : memoPageDescription}
        canonicalPath="/memo"
        structuredData={memoStructuredData}
      />
      <link rel="stylesheet" href="/memo/static/css/memo_form.css" precedence="memo" />

      <MemoPageControllerProvider>
        <MemoPageContent locale={locale} t={t} />
      </MemoPageControllerProvider>
    </>
  );
}

type MemoPageContentProps = Pick<ReturnType<typeof useTranslation>, "locale" | "t">;

// ページ骨格。ログイン状態・表示面（メモ／マイコンテキスト）・ゴミ箱かどうかで、出す部品を切り替える。
// Page shell; which parts appear depends on login state, the active view (memos or my context), and whether the trash is shown.
function MemoPageContent({ locale, t }: MemoPageContentProps) {
  const { isLoggedIn, authUiReady, isSidebarCollapsed, activeView, setActiveView, viewMode } = useMemoPageUiContext();
  const { archiveScope } = useMemoPageListContext();
  const { isBulkMode } = useMemoPageBoardContext();
  // ゴミ箱は読み取り専用の一覧なので、メモを書き始める入口（作成欄と新規作成ボタン）は出さない
  // The trash is a read-only list, so the ways to start a new memo (composer and new-memo button) are hidden
  const isTrashScope = archiveScope === "trash";

  return (
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
              {/* Short feature intro shown when logged out (provides crawlable public content) */}
              {!isLoggedIn && (
                <p className="memo-guest-intro">{t("memo.guestIntro")}</p>
              )}
              {/* ── ツールバー ──
                  ── Toolbar ── */}
              <MemoToolbar />

              <MemoCrawlSummary />

              {/* 一括操作バー
                  Bulk action bar */}
              {isBulkMode && (
                <MemoBulkBar />
              )}

              {/* ── クイック作成 ──
                  ── Quick capture ── */}
              {!isTrashScope && <MemoComposer />}

              <div className={`memo-board memo-board--${viewMode}${isTrashScope ? " memo-board--trash" : ""}`}>
                {/* ── メモ一覧 ──
                  ── Memo list ── */}
                <MemoHistoryPanel />
              </div>
              {isLoggedIn && !isBulkMode && !isTrashScope && <MemoNewFab />}
            </>
          )}
        </div>
      </div>

      {/* ── 画面下の通知（「元に戻す」付き） / Bottom notice with an undo ── */}
      <MemoPageFlashToast />

      {/* ── メモ詳細モーダル ──
          ── Memo detail modal ── */}
      <MemoDetailModal />

      {/* ── 共有モーダル ──
          ── Share modal ── */}
      <MemoShareModal />

      {/* ── コレクション管理パネル ──
          ── Collection management panel ── */}
      <MemoCollectionModal />

      {/* ── 書き出しモーダル ──
          ── Export modal ── */}
      <MemoExportModal />
    </div>
  );
}

// 通知の状態と操作を context から受け取り、トーストへ渡すだけの薄い橋渡し。
// Thin bridge that takes the notice state and actions from the context and hands them to the toast.
function MemoPageFlashToast() {
  const { flashState, runFlashAction, holdFlash, releaseFlash } = useMemoPageFlashContext();
  return <MemoFlashToast flash={flashState} onAction={runFlashAction} onHold={holdFlash} onRelease={releaseFlash} />;
}
