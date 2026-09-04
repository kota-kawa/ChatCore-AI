import { createContext, useContext, useMemo, type Context, type ReactNode } from "react";

// メモ画面の状態を子コンポーネントへ配る Context 群。
// 値の型は controller hook の戻り値から Pick で切り出すので、hook 側のキー変更が
// そのまま型エラーとして現れる。スライスは「誰が読むか」「どれくらい頻繁に変わるか」で分け、
// 変更頻度の高いスライスほど内側の Provider に置く。
// Context slices that distribute the memo page state to child components.
// Every slice type is a Pick over the controller hook's return type, so any key change
// in the hooks surfaces as a type error here. Slices are grouped by consumer and update
// frequency; the most frequently changing slice is the innermost provider.
export type MemoPageControllerState =
  ReturnType<typeof import("../../hooks/memo_page/use_memo_page_controller").useMemoPageController>;

// 認証状態とレイアウト系 UI 状態（更新頻度が低い）
// auth + layout-level UI state (changes rarely)
type MemoPageUiContextValue = Pick<
  MemoPageControllerState,
  | "isLoggedIn"
  | "authUiReady"
  | "viewMode"
  | "setViewMode"
  | "isFiltersOpen"
  | "setIsFiltersOpen"
  | "isSidebarCollapsed"
  | "setIsSidebarCollapsed"
  | "activeView"
  | "setActiveView"
>;

// 検索・並び替え・絞り込みと一覧データ、コレクション一覧
// search / sort / filter state, the list data and the collection list
type MemoPageListContextValue = Pick<
  MemoPageControllerState,
  | "query"
  | "setQuery"
  | "sortMode"
  | "setSortMode"
  | "archiveScope"
  | "setArchiveScope"
  | "activeCollectionId"
  | "setActiveCollectionId"
  | "hasActiveFilters"
  | "memos"
  | "totalMemoCount"
  | "memoLoadError"
  | "memoListLoading"
  | "collections"
  | "activeCollection"
>;

// 新規メモ作成フォーム
// the new-memo composer
type MemoPageComposerContextValue = Pick<
  MemoPageControllerState,
  | "formState"
  | "setFormState"
  | "previewMode"
  | "setPreviewMode"
  | "submitting"
  | "aiSuggesting"
  | "isComposePaletteOpen"
  | "setIsComposePaletteOpen"
  | "setIsComposeExpanded"
  | "composeTextareaRef"
  | "handleFormChange"
  | "handleSubmitMemo"
  | "handleAiSuggest"
  | "openTextComposer"
  | "openChecklistComposer"
  | "openComposePalette"
  | "hasComposeDraft"
  | "composeIsExpanded"
>;

// メモ一覧のカード操作・アクションメニュー・ドラッグ並べ替え・一括選択（最も頻繁に更新される）
// card actions, action menu, drag reorder and bulk selection on the board (changes most often)
type MemoPageBoardContextValue = Pick<
  MemoPageControllerState,
  | "openMenuMemoId"
  | "setOpenMenuMemoId"
  | "menuPosition"
  | "setMenuPosition"
  | "toggleMemoActionMenu"
  | "actionLoadingId"
  | "copyingMemoId"
  | "handleTogglePin"
  | "handleToggleArchive"
  | "handleDeleteMemo"
  | "copyMemoFullText"
  | "canDragMemos"
  | "canReorderCurrentView"
  | "draggedMemoId"
  | "cardRefs"
  | "pinnedMemos"
  | "otherMemos"
  | "handleMemoDragStart"
  | "handleMemoSectionDragOver"
  | "handleMemoDrop"
  | "clearMemoDragState"
  | "isBulkMode"
  | "setIsBulkMode"
  | "exitBulkMode"
  | "selectedIds"
  | "toggleSelectMemo"
  | "hasSelection"
  | "selectAll"
  | "deselectAll"
  | "executeBulkAction"
  | "bulkLoading"
  | "bulkCollectionId"
  | "setBulkCollectionId"
  | "openMemoDetail"
  | "openShareModal"
>;

// メモ詳細モーダル
// the memo detail modal
type MemoPageDetailContextValue = Pick<
  MemoPageControllerState,
  | "selectedMemo"
  | "isMemoDetailClosing"
  | "closeMemoDetail"
  | "detailEditBackgroundColor"
  | "setDetailEditBackgroundColor"
  | "detailPreviewMode"
  | "setDetailPreviewMode"
  | "detailEditTitle"
  | "setDetailEditTitle"
  | "detailEditCollectionId"
  | "setDetailEditCollectionId"
  | "copyDetailFullText"
  | "isMemoAgentOpen"
  | "setIsMemoAgentOpen"
  | "openMemoAgent"
  | "detailSaveStatus"
  | "detailHasUnsavedChanges"
  | "detailSaveError"
  | "detailLoading"
  | "detailError"
  | "detailEditAiResponse"
  | "setDetailEditAiResponse"
>;

// 共有・コレクション管理・エクスポートの各モーダル
// the share, collection-management and export modals
type MemoPageModalsContextValue = Pick<
  MemoPageControllerState,
  | "isShareModalOpen"
  | "closeShareModal"
  | "shareUrl"
  | "shareStatus"
  | "copyShareLink"
  | "openNativeShareSheet"
  | "shareLoading"
  | "supportsNativeShare"
  | "shareSnsLinks"
  | "isCollectionPanelOpen"
  | "setIsCollectionPanelOpen"
  | "newCollectionName"
  | "setNewCollectionName"
  | "newCollectionColor"
  | "setNewCollectionColor"
  | "collectionActionLoading"
  | "handleCreateCollection"
  | "editingCollectionId"
  | "setEditingCollectionId"
  | "editingCollectionName"
  | "setEditingCollectionName"
  | "editingCollectionColor"
  | "setEditingCollectionColor"
  | "handleUpdateCollection"
  | "handleDeleteCollection"
  | "isExportModalOpen"
  | "setIsExportModalOpen"
  | "exportFormat"
  | "setExportFormat"
  | "exportScope"
  | "setExportScope"
  | "exportSelectedIds"
  | "exportSelectedCount"
  | "allVisibleExportSelected"
  | "clearExportSelection"
  | "selectAllExportMemos"
  | "toggleExportMemo"
  | "canDownloadExport"
  | "handleExport"
>;

const MemoPageUiContext = createContext<MemoPageUiContextValue | null>(null);
const MemoPageListContext = createContext<MemoPageListContextValue | null>(null);
const MemoPageComposerContext = createContext<MemoPageComposerContextValue | null>(null);
const MemoPageBoardContext = createContext<MemoPageBoardContextValue | null>(null);
const MemoPageDetailContext = createContext<MemoPageDetailContextValue | null>(null);
const MemoPageModalsContext = createContext<MemoPageModalsContextValue | null>(null);

type MemoPageContextProviderProps = {
  controller: MemoPageControllerState;
  children: ReactNode;
};

// controller の戻り値をスライスごとに useMemo で切り出して配る。
// 各 useMemo はリテラルと依存配列に同じキーを列挙する（片方だけ変えると古い値が配られる）。
// Slice the controller output with one useMemo per context. Each useMemo lists the same
// keys in the literal and in the dependency array; changing only one side leaks stale values.
export function MemoPageContextProvider({ controller, children }: MemoPageContextProviderProps) {
  const uiValue = useMemo<MemoPageUiContextValue>(
    () => ({
      isLoggedIn: controller.isLoggedIn,
      authUiReady: controller.authUiReady,
      viewMode: controller.viewMode,
      setViewMode: controller.setViewMode,
      isFiltersOpen: controller.isFiltersOpen,
      setIsFiltersOpen: controller.setIsFiltersOpen,
      isSidebarCollapsed: controller.isSidebarCollapsed,
      setIsSidebarCollapsed: controller.setIsSidebarCollapsed,
      activeView: controller.activeView,
      setActiveView: controller.setActiveView,
    }),
    [
      controller.isLoggedIn,
      controller.authUiReady,
      controller.viewMode,
      controller.setViewMode,
      controller.isFiltersOpen,
      controller.setIsFiltersOpen,
      controller.isSidebarCollapsed,
      controller.setIsSidebarCollapsed,
      controller.activeView,
      controller.setActiveView,
    ],
  );

  const listValue = useMemo<MemoPageListContextValue>(
    () => ({
      query: controller.query,
      setQuery: controller.setQuery,
      sortMode: controller.sortMode,
      setSortMode: controller.setSortMode,
      archiveScope: controller.archiveScope,
      setArchiveScope: controller.setArchiveScope,
      activeCollectionId: controller.activeCollectionId,
      setActiveCollectionId: controller.setActiveCollectionId,
      hasActiveFilters: controller.hasActiveFilters,
      memos: controller.memos,
      totalMemoCount: controller.totalMemoCount,
      memoLoadError: controller.memoLoadError,
      memoListLoading: controller.memoListLoading,
      collections: controller.collections,
      activeCollection: controller.activeCollection,
    }),
    [
      controller.query,
      controller.setQuery,
      controller.sortMode,
      controller.setSortMode,
      controller.archiveScope,
      controller.setArchiveScope,
      controller.activeCollectionId,
      controller.setActiveCollectionId,
      controller.hasActiveFilters,
      controller.memos,
      controller.totalMemoCount,
      controller.memoLoadError,
      controller.memoListLoading,
      controller.collections,
      controller.activeCollection,
    ],
  );

  const composerValue = useMemo<MemoPageComposerContextValue>(
    () => ({
      formState: controller.formState,
      setFormState: controller.setFormState,
      previewMode: controller.previewMode,
      setPreviewMode: controller.setPreviewMode,
      submitting: controller.submitting,
      aiSuggesting: controller.aiSuggesting,
      isComposePaletteOpen: controller.isComposePaletteOpen,
      setIsComposePaletteOpen: controller.setIsComposePaletteOpen,
      setIsComposeExpanded: controller.setIsComposeExpanded,
      composeTextareaRef: controller.composeTextareaRef,
      handleFormChange: controller.handleFormChange,
      handleSubmitMemo: controller.handleSubmitMemo,
      handleAiSuggest: controller.handleAiSuggest,
      openTextComposer: controller.openTextComposer,
      openChecklistComposer: controller.openChecklistComposer,
      openComposePalette: controller.openComposePalette,
      hasComposeDraft: controller.hasComposeDraft,
      composeIsExpanded: controller.composeIsExpanded,
    }),
    [
      controller.formState,
      controller.setFormState,
      controller.previewMode,
      controller.setPreviewMode,
      controller.submitting,
      controller.aiSuggesting,
      controller.isComposePaletteOpen,
      controller.setIsComposePaletteOpen,
      controller.setIsComposeExpanded,
      controller.composeTextareaRef,
      controller.handleFormChange,
      controller.handleSubmitMemo,
      controller.handleAiSuggest,
      controller.openTextComposer,
      controller.openChecklistComposer,
      controller.openComposePalette,
      controller.hasComposeDraft,
      controller.composeIsExpanded,
    ],
  );

  const boardValue = useMemo<MemoPageBoardContextValue>(
    () => ({
      openMenuMemoId: controller.openMenuMemoId,
      setOpenMenuMemoId: controller.setOpenMenuMemoId,
      menuPosition: controller.menuPosition,
      setMenuPosition: controller.setMenuPosition,
      toggleMemoActionMenu: controller.toggleMemoActionMenu,
      actionLoadingId: controller.actionLoadingId,
      copyingMemoId: controller.copyingMemoId,
      handleTogglePin: controller.handleTogglePin,
      handleToggleArchive: controller.handleToggleArchive,
      handleDeleteMemo: controller.handleDeleteMemo,
      copyMemoFullText: controller.copyMemoFullText,
      canDragMemos: controller.canDragMemos,
      canReorderCurrentView: controller.canReorderCurrentView,
      draggedMemoId: controller.draggedMemoId,
      cardRefs: controller.cardRefs,
      pinnedMemos: controller.pinnedMemos,
      otherMemos: controller.otherMemos,
      handleMemoDragStart: controller.handleMemoDragStart,
      handleMemoSectionDragOver: controller.handleMemoSectionDragOver,
      handleMemoDrop: controller.handleMemoDrop,
      clearMemoDragState: controller.clearMemoDragState,
      isBulkMode: controller.isBulkMode,
      setIsBulkMode: controller.setIsBulkMode,
      exitBulkMode: controller.exitBulkMode,
      selectedIds: controller.selectedIds,
      toggleSelectMemo: controller.toggleSelectMemo,
      hasSelection: controller.hasSelection,
      selectAll: controller.selectAll,
      deselectAll: controller.deselectAll,
      executeBulkAction: controller.executeBulkAction,
      bulkLoading: controller.bulkLoading,
      bulkCollectionId: controller.bulkCollectionId,
      setBulkCollectionId: controller.setBulkCollectionId,
      openMemoDetail: controller.openMemoDetail,
      openShareModal: controller.openShareModal,
    }),
    [
      controller.openMenuMemoId,
      controller.setOpenMenuMemoId,
      controller.menuPosition,
      controller.setMenuPosition,
      controller.toggleMemoActionMenu,
      controller.actionLoadingId,
      controller.copyingMemoId,
      controller.handleTogglePin,
      controller.handleToggleArchive,
      controller.handleDeleteMemo,
      controller.copyMemoFullText,
      controller.canDragMemos,
      controller.canReorderCurrentView,
      controller.draggedMemoId,
      controller.cardRefs,
      controller.pinnedMemos,
      controller.otherMemos,
      controller.handleMemoDragStart,
      controller.handleMemoSectionDragOver,
      controller.handleMemoDrop,
      controller.clearMemoDragState,
      controller.isBulkMode,
      controller.setIsBulkMode,
      controller.exitBulkMode,
      controller.selectedIds,
      controller.toggleSelectMemo,
      controller.hasSelection,
      controller.selectAll,
      controller.deselectAll,
      controller.executeBulkAction,
      controller.bulkLoading,
      controller.bulkCollectionId,
      controller.setBulkCollectionId,
      controller.openMemoDetail,
      controller.openShareModal,
    ],
  );

  const detailValue = useMemo<MemoPageDetailContextValue>(
    () => ({
      selectedMemo: controller.selectedMemo,
      isMemoDetailClosing: controller.isMemoDetailClosing,
      closeMemoDetail: controller.closeMemoDetail,
      detailEditBackgroundColor: controller.detailEditBackgroundColor,
      setDetailEditBackgroundColor: controller.setDetailEditBackgroundColor,
      detailPreviewMode: controller.detailPreviewMode,
      setDetailPreviewMode: controller.setDetailPreviewMode,
      detailEditTitle: controller.detailEditTitle,
      setDetailEditTitle: controller.setDetailEditTitle,
      detailEditCollectionId: controller.detailEditCollectionId,
      setDetailEditCollectionId: controller.setDetailEditCollectionId,
      copyDetailFullText: controller.copyDetailFullText,
      isMemoAgentOpen: controller.isMemoAgentOpen,
      setIsMemoAgentOpen: controller.setIsMemoAgentOpen,
      openMemoAgent: controller.openMemoAgent,
      detailSaveStatus: controller.detailSaveStatus,
      detailHasUnsavedChanges: controller.detailHasUnsavedChanges,
      detailSaveError: controller.detailSaveError,
      detailLoading: controller.detailLoading,
      detailError: controller.detailError,
      detailEditAiResponse: controller.detailEditAiResponse,
      setDetailEditAiResponse: controller.setDetailEditAiResponse,
    }),
    [
      controller.selectedMemo,
      controller.isMemoDetailClosing,
      controller.closeMemoDetail,
      controller.detailEditBackgroundColor,
      controller.setDetailEditBackgroundColor,
      controller.detailPreviewMode,
      controller.setDetailPreviewMode,
      controller.detailEditTitle,
      controller.setDetailEditTitle,
      controller.detailEditCollectionId,
      controller.setDetailEditCollectionId,
      controller.copyDetailFullText,
      controller.isMemoAgentOpen,
      controller.setIsMemoAgentOpen,
      controller.openMemoAgent,
      controller.detailSaveStatus,
      controller.detailHasUnsavedChanges,
      controller.detailSaveError,
      controller.detailLoading,
      controller.detailError,
      controller.detailEditAiResponse,
      controller.setDetailEditAiResponse,
    ],
  );

  const modalsValue = useMemo<MemoPageModalsContextValue>(
    () => ({
      isShareModalOpen: controller.isShareModalOpen,
      closeShareModal: controller.closeShareModal,
      shareUrl: controller.shareUrl,
      shareStatus: controller.shareStatus,
      copyShareLink: controller.copyShareLink,
      openNativeShareSheet: controller.openNativeShareSheet,
      shareLoading: controller.shareLoading,
      supportsNativeShare: controller.supportsNativeShare,
      shareSnsLinks: controller.shareSnsLinks,
      isCollectionPanelOpen: controller.isCollectionPanelOpen,
      setIsCollectionPanelOpen: controller.setIsCollectionPanelOpen,
      newCollectionName: controller.newCollectionName,
      setNewCollectionName: controller.setNewCollectionName,
      newCollectionColor: controller.newCollectionColor,
      setNewCollectionColor: controller.setNewCollectionColor,
      collectionActionLoading: controller.collectionActionLoading,
      handleCreateCollection: controller.handleCreateCollection,
      editingCollectionId: controller.editingCollectionId,
      setEditingCollectionId: controller.setEditingCollectionId,
      editingCollectionName: controller.editingCollectionName,
      setEditingCollectionName: controller.setEditingCollectionName,
      editingCollectionColor: controller.editingCollectionColor,
      setEditingCollectionColor: controller.setEditingCollectionColor,
      handleUpdateCollection: controller.handleUpdateCollection,
      handleDeleteCollection: controller.handleDeleteCollection,
      isExportModalOpen: controller.isExportModalOpen,
      setIsExportModalOpen: controller.setIsExportModalOpen,
      exportFormat: controller.exportFormat,
      setExportFormat: controller.setExportFormat,
      exportScope: controller.exportScope,
      setExportScope: controller.setExportScope,
      exportSelectedIds: controller.exportSelectedIds,
      exportSelectedCount: controller.exportSelectedCount,
      allVisibleExportSelected: controller.allVisibleExportSelected,
      clearExportSelection: controller.clearExportSelection,
      selectAllExportMemos: controller.selectAllExportMemos,
      toggleExportMemo: controller.toggleExportMemo,
      canDownloadExport: controller.canDownloadExport,
      handleExport: controller.handleExport,
    }),
    [
      controller.isShareModalOpen,
      controller.closeShareModal,
      controller.shareUrl,
      controller.shareStatus,
      controller.copyShareLink,
      controller.openNativeShareSheet,
      controller.shareLoading,
      controller.supportsNativeShare,
      controller.shareSnsLinks,
      controller.isCollectionPanelOpen,
      controller.setIsCollectionPanelOpen,
      controller.newCollectionName,
      controller.setNewCollectionName,
      controller.newCollectionColor,
      controller.setNewCollectionColor,
      controller.collectionActionLoading,
      controller.handleCreateCollection,
      controller.editingCollectionId,
      controller.setEditingCollectionId,
      controller.editingCollectionName,
      controller.setEditingCollectionName,
      controller.editingCollectionColor,
      controller.setEditingCollectionColor,
      controller.handleUpdateCollection,
      controller.handleDeleteCollection,
      controller.isExportModalOpen,
      controller.setIsExportModalOpen,
      controller.exportFormat,
      controller.setExportFormat,
      controller.exportScope,
      controller.setExportScope,
      controller.exportSelectedIds,
      controller.exportSelectedCount,
      controller.allVisibleExportSelected,
      controller.clearExportSelection,
      controller.selectAllExportMemos,
      controller.toggleExportMemo,
      controller.canDownloadExport,
      controller.handleExport,
    ],
  );

  return (
    <MemoPageUiContext.Provider value={uiValue}>
      <MemoPageListContext.Provider value={listValue}>
        <MemoPageComposerContext.Provider value={composerValue}>
          <MemoPageDetailContext.Provider value={detailValue}>
            <MemoPageModalsContext.Provider value={modalsValue}>
              <MemoPageBoardContext.Provider value={boardValue}>{children}</MemoPageBoardContext.Provider>
            </MemoPageModalsContext.Provider>
          </MemoPageDetailContext.Provider>
        </MemoPageComposerContext.Provider>
      </MemoPageListContext.Provider>
    </MemoPageUiContext.Provider>
  );
}

function useRequiredContext<T>(context: Context<T | null>, contextName: string): T {
  const value = useContext(context);
  if (!value) {
    throw new Error(`${contextName} must be used within MemoPageContextProvider.`);
  }
  return value;
}

export function useMemoPageUiContext() {
  return useRequiredContext(MemoPageUiContext, "MemoPageUiContext");
}

export function useMemoPageListContext() {
  return useRequiredContext(MemoPageListContext, "MemoPageListContext");
}

export function useMemoPageComposerContext() {
  return useRequiredContext(MemoPageComposerContext, "MemoPageComposerContext");
}

export function useMemoPageBoardContext() {
  return useRequiredContext(MemoPageBoardContext, "MemoPageBoardContext");
}

export function useMemoPageDetailContext() {
  return useRequiredContext(MemoPageDetailContext, "MemoPageDetailContext");
}

export function useMemoPageModalsContext() {
  return useRequiredContext(MemoPageModalsContext, "MemoPageModalsContext");
}
