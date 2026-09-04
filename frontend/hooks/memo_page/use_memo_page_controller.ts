import { useMemoPageActionMenu } from "./use_memo_page_action_menu";
import { useMemoPageAuth } from "./use_memo_page_auth";
import { useMemoPageBulk } from "./use_memo_page_bulk";
import { useMemoPageChrome } from "./use_memo_page_chrome";
import { useMemoPageCollections } from "./use_memo_page_collections";
import { useMemoPageComposer } from "./use_memo_page_composer";
import { useMemoPageDetail } from "./use_memo_page_detail";
import { useMemoPageDrag } from "./use_memo_page_drag";
import { useMemoPageExport } from "./use_memo_page_export";
import { useMemoPageFlash } from "./use_memo_page_flash";
import { useMemoPageItemActions } from "./use_memo_page_item_actions";
import { useMemoPageLayout } from "./use_memo_page_layout";
import { useMemoPageList } from "./use_memo_page_list";
import { useMemoPageShare } from "./use_memo_page_share";

// メモ画面の機能別 hook を依存順に合成し、1 つのフラットなオブジェクトとして返す。
// 呼び出し順は依存関係で決まる（各 hook は自分より前の hook の値だけを受け取る）。
// 認証 hook の useLayoutEffect が drag hook の FLIP useLayoutEffect より先に走る順序も
// ここで保証している。
// Compose the memo page feature hooks in dependency order and return one flat object.
// Call order follows the dependency graph (each hook only consumes values from hooks
// above it), and it also guarantees that the auth layout effect runs before the FLIP
// layout effect inside the drag hook.
export function useMemoPageController() {
  const auth = useMemoPageAuth();
  const flash = useMemoPageFlash();
  const layout = useMemoPageLayout();
  const list = useMemoPageList();

  const collections = useMemoPageCollections({
    isLoggedIn: auth.isLoggedIn,
    activeCollectionId: list.activeCollectionId,
    setActiveCollectionId: list.setActiveCollectionId,
    mutate: list.mutate,
    showFlash: flash.showFlash,
  });

  const composer = useMemoPageComposer({
    mutate: list.mutate,
    showFlash: flash.showFlash,
    setFlashState: flash.setFlashState,
  });

  const detail = useMemoPageDetail({
    collections: collections.collections,
    mutate: list.mutate,
    showFlash: flash.showFlash,
  });

  const actionMenu = useMemoPageActionMenu();

  const bulk = useMemoPageBulk({
    memos: list.memos,
    collections: collections.collections,
    mutate: list.mutate,
    updateMemoListOptimistically: list.updateMemoListOptimistically,
    showFlash: flash.showFlash,
  });

  const drag = useMemoPageDrag({
    memos: list.memos,
    mutate: list.mutate,
    showFlash: flash.showFlash,
    archiveScope: list.archiveScope,
    sortMode: list.sortMode,
    query: list.query,
    isBulkMode: bulk.isBulkMode,
    closeMemoActionMenu: actionMenu.closeMemoActionMenu,
  });

  const itemActions = useMemoPageItemActions({
    mutate: list.mutate,
    updateMemoListOptimistically: list.updateMemoListOptimistically,
    showFlash: flash.showFlash,
    selectedMemoId: detail.selectedMemo?.id,
    patchSelectedMemoOptimistically: detail.patchSelectedMemoOptimistically,
    refreshSelectedMemoIfNeeded: detail.refreshSelectedMemoIfNeeded,
    startMemoDetailCloseAnimation: detail.startMemoDetailCloseAnimation,
  });

  const share = useMemoPageShare({
    mutate: list.mutate,
    showFlash: flash.showFlash,
  });

  const exporter = useMemoPageExport({
    memos: list.memos,
    showFlash: flash.showFlash,
  });

  useMemoPageChrome({
    selectedMemo: detail.selectedMemo,
    closeMemoDetail: detail.closeMemoDetail,
    isShareModalOpen: share.isShareModalOpen,
    setIsShareModalOpen: share.setIsShareModalOpen,
    isCollectionPanelOpen: collections.isCollectionPanelOpen,
    setIsCollectionPanelOpen: collections.setIsCollectionPanelOpen,
    isExportModalOpen: exporter.isExportModalOpen,
    setIsExportModalOpen: exporter.setIsExportModalOpen,
  });

  // 各 hook の戻り値キーは互いに素なので、そのまま展開して 1 つのオブジェクトにする
  // The hooks return disjoint key sets, so spreading them into one object is safe
  return {
    ...auth,
    ...flash,
    ...layout,
    ...list,
    ...collections,
    ...composer,
    ...detail,
    ...actionMenu,
    ...bulk,
    ...drag,
    ...itemActions,
    ...share,
    ...exporter,
  };
}
