// メモ画面の状態と操作を差し替えるテスト用スタブを提供する。
// Provides test stubs for memo page state and actions.

import type { MemoPageControllerState } from "../contexts/memo_page/memo_page_context";

// テスト用の controller スタブ。全キーを不活性なデフォルトで埋め、必要なものだけ上書きする。
// 完全な型で書いているので、controller のキーが増減・改名されると typecheck が落ちる（意図した契約）。
// Controller stub for tests: every key gets an inert default and tests override what they need.
// It is typed as the full controller state on purpose, so any key change in the controller
// fails `npm run typecheck` here.
const noop = () => undefined;
const asyncNoop = async () => undefined;
const asyncFalse = async () => false;

export const memoPageControllerStubDefaults: MemoPageControllerState = {
  // 認証状態。
  // auth
  isLoggedIn: false,
  authUiReady: true,
  currentUserId: null,
  // 一時通知。
  // flash
  flashState: null,
  setFlashState: noop,
  showFlash: noop,
  runFlashAction: noop,
  holdFlash: noop,
  releaseFlash: noop,
  // 配置状態。
  // layout
  activeView: "memos",
  setActiveView: noop,
  viewMode: "grid",
  setViewMode: noop,
  isFiltersOpen: false,
  setIsFiltersOpen: noop,
  isSidebarCollapsed: false,
  setIsSidebarCollapsed: noop,
  // 一覧状態。
  // list
  query: "",
  debouncedQuery: "",
  setQuery: noop,
  sortMode: "manual",
  setSortMode: noop,
  archiveScope: "active",
  setArchiveScope: noop,
  activeCollectionId: null,
  setActiveCollectionId: noop,
  memos: [],
  totalMemoCount: 0,
  remainingMemoCount: 0,
  canLoadMoreMemos: false,
  isLoadingMoreMemos: false,
  loadMoreMemos: noop,
  memoLoadError: undefined,
  memoListLoading: false,
  mutate: asyncNoop,
  updateMemoListOptimistically: asyncNoop,
  hasActiveFilters: false,
  // コレクション状態。
  // collections
  collections: [],
  mutateCollections: asyncNoop,
  activeCollection: null,
  isCollectionPanelOpen: false,
  setIsCollectionPanelOpen: noop,
  newCollectionName: "",
  setNewCollectionName: noop,
  newCollectionColor: "#6b7280",
  setNewCollectionColor: noop,
  collectionActionLoading: false,
  editingCollectionId: null,
  setEditingCollectionId: noop,
  editingCollectionName: "",
  setEditingCollectionName: noop,
  editingCollectionColor: "#6b7280",
  setEditingCollectionColor: noop,
  handleCreateCollection: asyncNoop,
  handleUpdateCollection: asyncNoop,
  handleDeleteCollection: asyncNoop,
  // 作成フォーム。
  // composer
  formState: { ai_response: "", title: "", collection_id: null, background_color: null },
  setFormState: noop,
  sourceMode: false,
  setSourceMode: noop,
  submitting: false,
  aiSuggesting: false,
  isComposePaletteOpen: false,
  setIsComposePaletteOpen: noop,
  setIsComposeExpanded: noop,
  composeEditorRef: { current: null },
  composeFocusRequest: 0,
  handleFormChange: noop,
  handleSubmitMemo: asyncNoop,
  handleAiSuggest: asyncNoop,
  openTextComposer: noop,
  openChecklistComposer: noop,
  openComposePalette: noop,
  hasComposeDraft: false,
  composeIsExpanded: false,
  // 詳細表示。
  // detail
  selectedMemo: null,
  isMemoDetailClosing: false,
  detailLoading: false,
  detailError: "",
  detailSourceMode: false,
  setDetailSourceMode: noop,
  detailEditTitle: "",
  setDetailEditTitle: noop,
  detailEditCollectionId: null,
  setDetailEditCollectionId: noop,
  detailEditAiResponse: "",
  setDetailEditAiResponse: noop,
  detailEditBackgroundColor: null,
  setDetailEditBackgroundColor: noop,
  detailSaveStatus: "idle",
  detailSaveError: "",
  isMemoAgentOpen: false,
  setIsMemoAgentOpen: noop,
  detailHasUnsavedChanges: false,
  openMemoDetail: asyncFalse,
  closeMemoDetail: asyncNoop,
  openMemoAgent: asyncNoop,
  saveDetailEdit: async () => true,
  copyDetailFullText: asyncFalse,
  patchSelectedMemoOptimistically: noop,
  refreshSelectedMemoIfNeeded: asyncNoop,
  startMemoDetailCloseAnimation: noop,
  // 操作メニュー。
  // action menu
  openMenuMemoId: "",
  setOpenMenuMemoId: noop,
  menuPosition: null,
  setMenuPosition: noop,
  closeMemoActionMenu: noop,
  toggleMemoActionMenu: noop,
  // 一括操作。
  // bulk
  isBulkMode: false,
  setIsBulkMode: noop,
  selectedIds: new Set<string>(),
  bulkCollectionId: null,
  setBulkCollectionId: noop,
  bulkLoading: false,
  hasSelection: false,
  toggleSelectMemo: noop,
  selectAll: noop,
  deselectAll: noop,
  executeBulkAction: asyncNoop,
  exitBulkMode: noop,
  // ドラッグ操作。
  // drag
  canDragMemos: false,
  canReorderCurrentView: false,
  draggedMemoId: "",
  cardRefs: { current: new Map<string, HTMLElement>() },
  displayMemos: [],
  pinnedMemos: [],
  otherMemos: [],
  clearMemoDragState: noop,
  handleMemoDragStart: noop,
  handleMemoSectionDragOver: noop,
  handleMemoDrop: asyncNoop,
  // 項目ごとの操作。
  // item actions
  actionLoadingId: "",
  copyingMemoId: "",
  handleTogglePin: asyncNoop,
  handleToggleMemoTask: asyncNoop,
  handleToggleArchive: asyncNoop,
  handleDeleteMemo: asyncNoop,
  handleRestoreMemo: asyncNoop,
  handlePurgeMemo: asyncNoop,
  handleEmptyTrash: asyncNoop,
  emptyingTrash: false,
  copyMemoFullText: asyncFalse,
  // 共有操作。
  // share
  isShareModalOpen: false,
  setIsShareModalOpen: noop,
  shareUrl: "",
  shareStatus: null,
  shareLoading: false,
  supportsNativeShare: false,
  shareSnsLinks: { x: "", line: "", facebook: "" },
  openShareModal: asyncNoop,
  closeShareModal: noop,
  copyShareLink: asyncFalse,
  openNativeShareSheet: asyncNoop,
  // エクスポート。
  // export
  isExportModalOpen: false,
  setIsExportModalOpen: noop,
  exportFormat: "markdown",
  setExportFormat: noop,
  exportScope: "all",
  setExportScope: noop,
  exportSelectedIds: new Set<string>(),
  exportSelectedCount: 0,
  allVisibleExportSelected: false,
  canDownloadExport: true,
  toggleExportMemo: noop,
  selectAllExportMemos: noop,
  clearExportSelection: noop,
  handleExport: noop,
};

export function createMemoPageControllerStub(
  overrides: Partial<MemoPageControllerState> = {},
): MemoPageControllerState {
  return { ...memoPageControllerStubDefaults, ...overrides };
}
