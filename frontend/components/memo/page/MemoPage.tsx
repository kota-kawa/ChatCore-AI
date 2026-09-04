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
// ここでは controller から受け取った値を子コンポーネントへ配るだけにする。
// Main page component for the memo feature. State and actions live in the feature hooks
// under hooks/memo_page/; this component only wires the controller output into children.
export default function MemoPage() {
  const { locale, t } = useTranslation();
  const controller = useMemoPageController();

  const {
    // auth
    isLoggedIn,
    authUiReady,
    // flash
    flashState,
    // layout
    activeView,
    setActiveView,
    viewMode,
    setViewMode,
    isFiltersOpen,
    setIsFiltersOpen,
    isSidebarCollapsed,
    setIsSidebarCollapsed,
    // list
    query,
    setQuery,
    sortMode,
    setSortMode,
    archiveScope,
    setArchiveScope,
    activeCollectionId,
    setActiveCollectionId,
    memos,
    totalMemoCount,
    memoLoadError,
    memoListLoading,
    hasActiveFilters,
    // collections
    collections,
    activeCollection,
    isCollectionPanelOpen,
    setIsCollectionPanelOpen,
    newCollectionName,
    setNewCollectionName,
    newCollectionColor,
    setNewCollectionColor,
    collectionActionLoading,
    editingCollectionId,
    setEditingCollectionId,
    editingCollectionName,
    setEditingCollectionName,
    editingCollectionColor,
    setEditingCollectionColor,
    handleCreateCollection,
    handleUpdateCollection,
    handleDeleteCollection,
    // composer
    formState,
    setFormState,
    previewMode,
    setPreviewMode,
    submitting,
    aiSuggesting,
    isComposePaletteOpen,
    setIsComposePaletteOpen,
    setIsComposeExpanded,
    composeTextareaRef,
    handleFormChange,
    handleSubmitMemo,
    handleAiSuggest,
    openTextComposer,
    openChecklistComposer,
    openComposePalette,
    hasComposeDraft,
    composeIsExpanded,
    // detail
    selectedMemo,
    isMemoDetailClosing,
    detailLoading,
    detailError,
    detailPreviewMode,
    setDetailPreviewMode,
    detailEditTitle,
    setDetailEditTitle,
    detailEditCollectionId,
    setDetailEditCollectionId,
    detailEditAiResponse,
    setDetailEditAiResponse,
    detailEditBackgroundColor,
    setDetailEditBackgroundColor,
    detailSaveStatus,
    detailSaveError,
    isMemoAgentOpen,
    setIsMemoAgentOpen,
    detailHasUnsavedChanges,
    openMemoDetail,
    closeMemoDetail,
    openMemoAgent,
    copyDetailFullText,
    // action menu
    openMenuMemoId,
    setOpenMenuMemoId,
    menuPosition,
    setMenuPosition,
    toggleMemoActionMenu,
    // bulk
    isBulkMode,
    setIsBulkMode,
    selectedIds,
    bulkCollectionId,
    setBulkCollectionId,
    bulkLoading,
    hasSelection,
    toggleSelectMemo,
    selectAll,
    deselectAll,
    executeBulkAction,
    exitBulkMode,
    // drag
    canDragMemos,
    canReorderCurrentView,
    draggedMemoId,
    cardRefs,
    pinnedMemos,
    otherMemos,
    clearMemoDragState,
    handleMemoDragStart,
    handleMemoSectionDragOver,
    handleMemoDrop,
    // item actions
    actionLoadingId,
    copyingMemoId,
    handleTogglePin,
    handleToggleArchive,
    handleDeleteMemo,
    copyMemoFullText,
    // share
    isShareModalOpen,
    shareUrl,
    shareStatus,
    shareLoading,
    supportsNativeShare,
    shareSnsLinks,
    openShareModal,
    closeShareModal,
    copyShareLink,
    openNativeShareSheet,
    // export
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
  } = controller;

  return (
    <>
      <SeoHead
        title={t("memo.title")}
        description={locale === "en" ? "Save, organize, search, and share your notes and useful AI responses." : memoPageDescription}
        canonicalPath="/memo"
        structuredData={memoStructuredData}
      />

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
          <MemoSidebar
            isSidebarCollapsed={isSidebarCollapsed}
            setIsSidebarCollapsed={setIsSidebarCollapsed}
            activeCollectionId={activeCollectionId}
            setActiveCollectionId={setActiveCollectionId}
            archiveScope={archiveScope}
            setArchiveScope={setArchiveScope}
            sortMode={sortMode}
            setSortMode={setSortMode}
            collections={collections}
            setIsCollectionPanelOpen={setIsCollectionPanelOpen}
            activeView={activeView}
            setActiveView={setActiveView}
          />

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
            <MemoToolbar
              activeCollection={activeCollection}
              activeCollectionId={activeCollectionId}
              archiveScope={archiveScope}
              sortMode={sortMode}
              collections={collections}
              totalMemoCount={totalMemoCount}
              query={query}
              setQuery={setQuery}
              hasActiveFilters={hasActiveFilters}
              setArchiveScope={setArchiveScope}
              setSortMode={setSortMode}
              setActiveCollectionId={setActiveCollectionId}
              viewMode={viewMode}
              setViewMode={setViewMode}
              isBulkMode={isBulkMode}
              exitBulkMode={exitBulkMode}
              setIsBulkMode={setIsBulkMode}
              setIsExportModalOpen={setIsExportModalOpen}
              isFiltersOpen={isFiltersOpen}
              setIsFiltersOpen={setIsFiltersOpen}
              setIsCollectionPanelOpen={setIsCollectionPanelOpen}
            />

          {flashState && (
            <div className={`memo-flash memo-flash--${flashState.type}`} role="alert">
              {flashState.text}
            </div>
          )}

          <MemoCrawlSummary />

          {/* Bulk action bar */}
          {isBulkMode && (
            <MemoBulkBar
              hasSelection={hasSelection}
              selectedIds={selectedIds}
              memos={memos}
              selectAll={selectAll}
              deselectAll={deselectAll}
              executeBulkAction={executeBulkAction}
              bulkLoading={bulkLoading}
              collections={collections}
              bulkCollectionId={bulkCollectionId}
              setBulkCollectionId={setBulkCollectionId}
            />
          )}

          {/* ── Quick capture ── */}
          <MemoComposer
            composeIsExpanded={composeIsExpanded}
            openTextComposer={openTextComposer}
            openChecklistComposer={openChecklistComposer}
            openComposePalette={openComposePalette}
            handleSubmitMemo={handleSubmitMemo}
            formState={formState}
            handleFormChange={handleFormChange}
            previewMode={previewMode}
            setPreviewMode={setPreviewMode}
            composeTextareaRef={composeTextareaRef}
            collections={collections}
            setFormState={setFormState}
            aiSuggesting={aiSuggesting}
            handleAiSuggest={handleAiSuggest}
            isComposePaletteOpen={isComposePaletteOpen}
            submitting={submitting}
            setIsComposeExpanded={setIsComposeExpanded}
            setIsComposePaletteOpen={setIsComposePaletteOpen}
            hasComposeDraft={hasComposeDraft}
          />

          <div className={`memo-board memo-board--${viewMode}`}>
            {/* ── Memo list ── */}
            <MemoHistoryPanel
              activeCollection={activeCollection}
              totalMemoCount={totalMemoCount}
              memoLoadError={memoLoadError}
              memoListLoading={memoListLoading}
              memos={memos}
              pinnedMemos={pinnedMemos}
              otherMemos={otherMemos}
              openMenuMemoId={openMenuMemoId}
              actionLoadingId={actionLoadingId}
              selectedIds={selectedIds}
              copyingMemoId={copyingMemoId}
              canDragMemos={canDragMemos}
              draggedMemoId={draggedMemoId}
              cardRefs={cardRefs}
              isBulkMode={isBulkMode}
              menuPosition={menuPosition}
              canReorderCurrentView={canReorderCurrentView}
              handleMemoDragStart={handleMemoDragStart}
              clearMemoDragState={clearMemoDragState}
              toggleSelectMemo={toggleSelectMemo}
              handleTogglePin={handleTogglePin}
              openMemoDetail={openMemoDetail}
              copyMemoFullText={copyMemoFullText}
              handleToggleArchive={handleToggleArchive}
              toggleMemoActionMenu={toggleMemoActionMenu}
              openShareModal={openShareModal}
              setOpenMenuMemoId={setOpenMenuMemoId}
              setMenuPosition={setMenuPosition}
              handleDeleteMemo={handleDeleteMemo}
              handleMemoSectionDragOver={handleMemoSectionDragOver}
              handleMemoDrop={handleMemoDrop}
            />
          </div>
            </>
            )}
          </div>
        </div>

        {/* ── Memo detail modal ── */}
        <MemoDetailModal
          selectedMemo={selectedMemo}
          isMemoDetailClosing={isMemoDetailClosing}
          closeMemoDetail={closeMemoDetail}
          detailEditBackgroundColor={detailEditBackgroundColor}
          setDetailEditBackgroundColor={setDetailEditBackgroundColor}
          detailPreviewMode={detailPreviewMode}
          setDetailPreviewMode={setDetailPreviewMode}
          detailEditTitle={detailEditTitle}
          setDetailEditTitle={setDetailEditTitle}
          collections={collections}
          detailEditCollectionId={detailEditCollectionId}
          setDetailEditCollectionId={setDetailEditCollectionId}
          copyDetailFullText={copyDetailFullText}
          isMemoAgentOpen={isMemoAgentOpen}
          setIsMemoAgentOpen={setIsMemoAgentOpen}
          openMemoAgent={openMemoAgent}
          detailSaveStatus={detailSaveStatus}
          detailHasUnsavedChanges={detailHasUnsavedChanges}
          detailSaveError={detailSaveError}
          detailLoading={detailLoading}
          detailError={detailError}
          detailEditAiResponse={detailEditAiResponse}
          setDetailEditAiResponse={setDetailEditAiResponse}
        />

        {/* ── Share modal ── */}
        <MemoShareModal
          isShareModalOpen={isShareModalOpen}
          closeShareModal={closeShareModal}
          shareUrl={shareUrl}
          shareStatus={shareStatus}
          copyShareLink={copyShareLink}
          openNativeShareSheet={openNativeShareSheet}
          shareLoading={shareLoading}
          supportsNativeShare={supportsNativeShare}
          shareSnsLinks={shareSnsLinks}
        />

        {/* ── Collection management panel ── */}
        <MemoCollectionModal
          isCollectionPanelOpen={isCollectionPanelOpen}
          setIsCollectionPanelOpen={setIsCollectionPanelOpen}
          collections={collections}
          newCollectionName={newCollectionName}
          setNewCollectionName={setNewCollectionName}
          newCollectionColor={newCollectionColor}
          setNewCollectionColor={setNewCollectionColor}
          collectionActionLoading={collectionActionLoading}
          handleCreateCollection={handleCreateCollection}
          editingCollectionId={editingCollectionId}
          setEditingCollectionId={setEditingCollectionId}
          editingCollectionName={editingCollectionName}
          setEditingCollectionName={setEditingCollectionName}
          editingCollectionColor={editingCollectionColor}
          setEditingCollectionColor={setEditingCollectionColor}
          handleUpdateCollection={handleUpdateCollection}
          handleDeleteCollection={handleDeleteCollection}
        />

        {/* ── Export modal ── */}
        <MemoExportModal
          isExportModalOpen={isExportModalOpen}
          setIsExportModalOpen={setIsExportModalOpen}
          exportFormat={exportFormat}
          setExportFormat={setExportFormat}
          exportScope={exportScope}
          setExportScope={setExportScope}
          exportSelectedIds={exportSelectedIds}
          exportSelectedCount={exportSelectedCount}
          allVisibleExportSelected={allVisibleExportSelected}
          clearExportSelection={clearExportSelection}
          selectAllExportMemos={selectAllExportMemos}
          toggleExportMemo={toggleExportMemo}
          canDownloadExport={canDownloadExport}
          handleExport={handleExport}
          memos={memos}
        />
      </div>
    </>
  );
}
